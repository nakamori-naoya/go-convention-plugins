# query service とは何か

**query service とは、テーブルの行を読み取りモデル（DTO）へ写すものである。** CQRS の読み取り側で、一覧・件数・検索・空き状況のような「見せるための形」を SQL で作り、行を DTO へ詰めて usecase に返す。それ以外のことをしない。

これは、**集約を復元する場所ではない**。ドメイン（集約・VO）を import せず、`New*` も `Restore*` も呼ばない。**書き込む場所でもない**。SELECT しか発行しない。**業務判断の置き場でもない**。何を許し何を拒むかは集約が決め、読み取りモデルはテーブルにある事実を写すだけである。**トランザクションの持ち主でもない**。usecase が張った tx があればそれに乗り、無ければ pool で読む。

## 1. する／しない

| する | しない |
|---|---|
| 一覧・件数・検索・ページング・ソート・フィルタ・JOIN・集計を **SQL で** 行う | Go 側で並べ替える・絞り込む・数える・突き合わせる（SQL に書けることを Go に持ち出さない） |
| 行 → DTO を純粋関数で写す（[dto.md](dto.md) §4） | ドメインの `New*` / `Restore*` を呼ぶ。集約・VO の型を返す・受け取る |
| NULL 許可列を `(T, bool)` に写し、DTO では値と有無の対にする | NULL を既定の値（0・空文字・ゼロ時刻）へ丸めて有無を消す |
| 時刻を `.UTC()` で正規化し、日付の引数が UTC の 0 時であることを確かめる | 引数の時刻部分を切り捨てて「日付」にする。`time.Now()` を呼ぶ（日付は引数で受ける） |
| `limit` の範囲外・`offset` の負を error で拒む | 未指定・範囲外を既定値へ丸める |
| ctx に tx があればそれで、無ければ pool で読む（§3） | `Begin` / `Commit` / `Rollback` を呼ぶ。`SELECT ... FOR UPDATE` で行をロックする |
| `:one` の `pgx.ErrNoRows` を `query.ErrNotFound` に翻訳し、文脈を 1 回足して返す | リポジトリ（永続化ポート）を呼ぶ。`rdb` package を import する |
| sqlc の生成メソッドを直接呼ぶ（読み取り専用 query ファイル。§4） | INSERT / UPDATE / DELETE を発行する（閲覧記録・最終アクセス日時の更新も含む） |
| 引数の形の検査（範囲・日付の形）だけ | 業務の妥当性判断（会議室が存在するか・顧客が申込可能か）。キャッシュ・リトライ・ログ |

「する」列に無いものは書かない。迷ったら「しない」に倒し、置き場が分からなければ停止条件で返す。

## 2. 依存の向きと置き場

```
handler ──▶ usecase（読み取りポート interface を定義）
   │            │
   │ DTO を      │ DTO を返り値の型として使う
   │ proto へ    ▼
   └────────▶ query（DTO・query 型・行 → DTO）   ← 実装がポートを満たす。query は usecase を import しない
                 │
                 ├──▶ rdb/sqlcgen（sqlc 生成。永続化と共有）
                 ├──▶ tx（`From` だけ）
                 └──▶ pgx（`pgxpool` / `pgtype`）
```

- **読み取りポートは usecase 側が定義する。** usecase が使うメソッドだけを interface に切り、`query` の型がそれを満たす。`query` package は interface を定義しない
- `query` は `reservation`（ドメイン）と `rdb`（永続化）を import しない。共有するのは sqlc の生成物 `rdb/sqlcgen` と `tx` だけ
- query 型は `*pgxpool.Pool` を 1 つ持つ（`NewRoomAvailabilityQuery(pool)`）。ロガー・時計・キャッシュを持たない

```go
package usecase

import (
	"context"
	"time"

	"example.com/roomflow/query"
)

// RoomAvailabilityReader は空き状況の読み取りポート。usecase が使う分だけ切り、query package の型が満たす。
type RoomAvailabilityReader interface {
	ListForDay(ctx context.Context, room string, day time.Time) (query.RoomAvailability, error)
}

// ActiveReservationReader / NoShowReader は仮押さえの command が材料を読む読み取りポート（§8）。
type ActiveReservationReader interface {
	ListActiveOverlapping(ctx context.Context, roomCode string, startsAt, endsAt time.Time) ([]query.ActiveSlot, error)
}

type NoShowReader interface {
	ListNoShowAt(ctx context.Context, customerCode string) ([]time.Time, error)
}
```

ディレクトリ構成そのものは上位の開発規約が決める。この skill の例は import path を短くするため平らにしている（module `example.com/roomflow`）。

| path | 中身 |
|---|---|
| `query/room_availability.go` | `RoomAvailabilityQuery` と `ListForDay`、DTO `RoomAvailability` / `AvailableSlot` |
| `query/room_availability_marshaller.go` | 行 → DTO の純粋関数（`{Row}To{DTO}`） |
| `query/active_reservation.go` | `ActiveReservationQuery` と `ListActiveOverlapping`、DTO `ActiveSlot`（§8） |
| `query/no_show.go` | `NoShowQuery` と `ListNoShowAt`（§8） |
| `query/due_hold.go` | `DueHoldQuery` と `ListDueHoldIDs`（§8） |
| `query/reservation_history.go` | `ReservationHistoryQuery`（ページングと件数の例）と DTO |
| `query/page.go` | `Page` と `MaxPageLimit` |
| `query/queries.go` | `queries(ctx, pool)`（§3） |
| `query/errors.go` | `query` package の sentinel（§7） |
| `rdb/query/{name}_read.sql` | 読み取り専用の sqlc query ファイル（§4） |
| `rdb/sqlcgen/` | sqlc の生成物。永続化と同じ package で、手で編集しない |

## 3. 接続: tx か pool か

読み取りに tx は要らない。ただし usecase が tx を張って（`tx.Manager.Run` の中で）query service を呼んだら、同じ tx で読む。同じ tx で書いた行をその tx の中で読めなければ、usecase の手順が壊れるからである。

```go
package query

import (
	"context"

	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/rdb/sqlcgen"
	"example.com/roomflow/tx"
)

// queries は、usecase が張った tx が ctx にあればその tx で、無ければ pool で読む sqlc の Queries を返す。
func queries(ctx context.Context, pool *pgxpool.Pool) *sqlcgen.Queries {
	if t, ok := tx.From(ctx); ok {
		return sqlcgen.New(t)
	}
	return sqlcgen.New(pool)
}
```

| 規則 | 理由 |
|---|---|
| 選択は ctx の tx の有無で決まる。query service が tx を張らず、tx の有無で error にもしない | 読み取りは単文で完結し、部分失敗が残らない。usecase が tx を張るかは usecase が決め、query service はそれに乗るだけ |
| `Queries` はメソッド呼び出しごとに作り、struct に持たない | struct に持つと ctx の tx と食い違う |
| `pgx.Tx` / `*pgxpool.Pool` を引数・返り値に出さない | ctx と struct のフィールドだけが運ぶ。ポートに DB の型が漏れない |
| `SELECT ... FOR UPDATE` / `FOR SHARE` を書かない | ロックを取る読み取りは集約の操作の前段で、リポジトリと usecase の関心 |

## 4. sqlc の読み取り専用 query ファイル

SQL は sqlc の query ファイルにだけ書き、生成メソッドを直接呼ぶ。`sqlc.yaml` と生成先は永続化と共有し（`sql_package: "pgx/v5"`、NOT NULL の `timestamptz` は `time.Time` への override）、読み取り用の `Queries` 型を別に作らない。

| 項目 | 規則 |
|---|---|
| 置き場 | `rdb/query/{name}_read.sql`。読み取りモデル 1 つ（query 型 1 つ）に 1 ファイル。`_read` 接尾辞で永続化の query ファイルと区別する |
| 中身 | SELECT だけ。INSERT / UPDATE / DELETE / `FOR UPDATE` を書かない |
| 名前 | `{List\|Get\|Count}{何}`。`ListRoomSlotsForDay` / `GetReservationSummary` / `CountCustomerReservations` |
| 注釈 | 複数行 `:many`、1 行 `:one`（`count(*)` も `:one`）。`:exec` / `:execrows` は現れない |
| 読む列 | DTO に要る列だけを明示する（`SELECT *` を書かない）。JOIN で複数テーブルから読むので、行の型は query ごとに sqlc が生む `{QueryName}Row` になる |
| 引数 | 列名と同じ位置引数 `$n`。列名から取れない引数（日付の範囲）だけ `sqlc.arg(day_start)` で名前を付ける |
| フィルタ・ソート・範囲 | すべて SQL。`ORDER BY` は結果が一意に並ぶよう末尾に主キーを足す |
| テスト用の query | 投入・全行読み取りをこのファイルに足さない。置き場と形はテストの規約が決める |

題材の `rdb/query/room_availability_read.sql`。占有中の枠（`room_booking_claims`）に予約の状態と、仮押さえのときだけある期限を LEFT JOIN で付ける:

```sql
-- name: ListRoomSlotsForDay :many
SELECT c.reservation_id, c.starts_at, c.ends_at, r.status, d.expires_at
FROM room_booking_claims c
JOIN reservations r ON r.reservation_id = c.reservation_id
LEFT JOIN tentative_hold_deadlines d ON d.reservation_id = c.reservation_id
WHERE c.room_code = $1
  AND c.ends_at > sqlc.arg(day_start)
  AND c.starts_at < sqlc.arg(day_end)
ORDER BY c.starts_at, c.reservation_id;
```

生成されるシグネチャと行の型（sqlc が決める。LEFT JOIN 側の列は NULL 許可として `pgtype` になる）:

```go
type ListRoomSlotsForDayParams struct {
	RoomCode string
	DayStart time.Time
	DayEnd   time.Time
}

type ListRoomSlotsForDayRow struct {
	ReservationID string
	StartsAt      time.Time
	EndsAt        time.Time
	Status        string
	ExpiresAt     pgtype.Timestamptz
}

func (q *Queries) ListRoomSlotsForDay(ctx context.Context, arg ListRoomSlotsForDayParams) ([]ListRoomSlotsForDayRow, error)
```

## 5. メソッドの形

引数の形を確かめる → `queries(ctx, q.pool)` → 生成メソッドを 1 回呼ぶ → 行 → DTO → 返す。この 5 つ以外を書かない。

```go
package query

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/rdb/sqlcgen"
)

type RoomAvailabilityQuery struct{ pool *pgxpool.Pool }

func NewRoomAvailabilityQuery(pool *pgxpool.Pool) *RoomAvailabilityQuery {
	return &RoomAvailabilityQuery{pool: pool}
}

// ListForDay は、会議室 room の day（UTC の 0 時）から 24 時間に掛かる占有中の利用枠を開始時刻順に返す。
// 日をまたぐ枠は両方の日に現れる。占有が無ければ Slots は nil。
func (q *RoomAvailabilityQuery) ListForDay(ctx context.Context, room string, day time.Time) (RoomAvailability, error) {
	dayStart, err := utcDate(day)
	if err != nil {
		return RoomAvailability{}, fmt.Errorf("会議室 %s の空き状況: %w", room, err)
	}
	rows, err := queries(ctx, q.pool).ListRoomSlotsForDay(ctx, sqlcgen.ListRoomSlotsForDayParams{
		RoomCode: room,
		DayStart: dayStart,
		DayEnd:   dayStart.AddDate(0, 0, 1),
	})
	if err != nil {
		return RoomAvailability{}, fmt.Errorf("会議室 %s の空き状況: %w", room, err)
	}
	return listRoomSlotsForDayRowsToRoomAvailability(room, rows), nil
}

// utcDate は day が UTC の 0 時ちょうどであることを確かめて返す。時刻部分を切り捨てて丸めない。
func utcDate(day time.Time) (time.Time, error) {
	u := day.UTC()
	d := time.Date(u.Year(), u.Month(), u.Day(), 0, 0, 0, 0, time.UTC)
	if !u.Equal(d) {
		return time.Time{}, ErrDayHasClock
	}
	return d, nil
}
```

| 規則 | 理由 |
|---|---|
| 引数の検査は「SQL に渡せる形か」だけ（日付の形・`limit` の範囲）。会議室の存在や顧客の資格は見ない | 業務の妥当性は集約の関心。読み取りは行が無ければ空を返す |
| 生成メソッドは 1 メソッド 1 回。件数が要るなら別メソッド（§6） | N+1 と「一覧 + 件数」の抱き合わせを避ける。件数が要らない呼び手に COUNT を払わせない |
| 文脈は `fmt.Errorf("会議室 %s の空き状況: %w", room, err)` で 1 メソッド 1 回。SQL 文・テーブル名を文言に入れない | 境界が 1 回記録する。内側でログしない |
| 分岐は引数検査のガード節と `err != nil` だけ。行の値で分岐しない | 行の値による分岐は SQL の `WHERE` か DTO の有無の対で表す |

`:one` は行が無いとき `pgx.ErrNoRows` を返す。query service の中で `query.ErrNotFound` に翻訳する（`ReservationSummary` は予約 1 件の概要 DTO。`GetReservationSummary` は `reservations` を主キーで 1 行読む `:one`）。

```go
	row, err := queries(ctx, q.pool).GetReservationSummary(ctx, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return ReservationSummary{}, fmt.Errorf("予約 %s の概要: %w", id, ErrNotFound)
	}
	if err != nil {
		return ReservationSummary{}, fmt.Errorf("予約 %s の概要: %w", id, err)
	}
	return getReservationSummaryRowToReservationSummary(row), nil
```

## 6. ページング・件数・フィルタ

置き場は SQL。Go 側は範囲を検査して渡すだけ。

| 項目 | 規則 |
|---|---|
| ページング | `LIMIT $n OFFSET $m`。`limit` は 1 以上 `MaxPageLimit` 以下、`offset` は 0 以上。範囲外は error で、既定値へ丸めない |
| 上限 | `MaxPageLimit` は `query` package の定数 1 つ。読み取りモデルごとに変えない |
| 親子を持つ一覧のページング | 親の表に `LIMIT` を掛けてから子を JOIN する（サブクエリ）。JOIN した結果に `LIMIT` を掛けると親が途中で切れる |
| 件数 | `count(*)` の `:one` を別 query・別メソッドにする。一覧と同じ `WHERE` を持つ |
| フィルタ | `WHERE` に書く。引数の組み合わせで SQL を組み立てない（条件が違えば query を分ける） |
| ソート | `ORDER BY` に書き、末尾に主キーを足して一意にする。呼び手からソート列を受け取らない（要るなら query を分ける） |

```go
package query

// MaxPageLimit は 1 回の一覧で返す最大件数。超える要求は ErrPageLimitOutOfRange。
const MaxPageLimit = 100

type Page struct {
	Limit  int // 1 以上 MaxPageLimit 以下
	Offset int // 0 以上
}

// validate は範囲外を sentinel で返す。文脈（どの読み取りか）は呼んだメソッドが 1 回足す。
func (p Page) validate() error {
	if p.Limit < 1 || p.Limit > MaxPageLimit {
		return ErrPageLimitOutOfRange
	}
	if p.Offset < 0 {
		return ErrPageOffsetNegative
	}
	return nil
}
```

題材の `rdb/query/reservation_history_read.sql`。顧客の予約を新しい順にページングし、各予約に起きた出来事（基底イベント）を version 順に付ける:

```sql
-- name: ListCustomerHistory :many
SELECT r.reservation_id, r.room_code, r.starts_at, r.ends_at, r.status,
       e.version, e.event_type, e.actor_code, e.occurred_at
FROM reservations r
JOIN reservation_base_events e ON e.reservation_id = r.reservation_id
WHERE r.reservation_id IN (
    SELECT reservation_id
    FROM reservations
    WHERE customer_code = $1
    ORDER BY starts_at DESC, reservation_id
    LIMIT $2 OFFSET $3
)
ORDER BY r.starts_at DESC, r.reservation_id, e.version;

-- name: CountCustomerReservations :one
SELECT count(*) FROM reservations WHERE customer_code = $1;
```

```go
package query

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/rdb/sqlcgen"
)

type ReservationHistoryQuery struct{ pool *pgxpool.Pool }

func NewReservationHistoryQuery(pool *pgxpool.Pool) *ReservationHistoryQuery {
	return &ReservationHistoryQuery{pool: pool}
}

// ListByCustomer は、顧客 customer の予約を利用開始の新しい順に page の範囲で返す。各予約の Events は version 順。
func (q *ReservationHistoryQuery) ListByCustomer(ctx context.Context, customer string, page Page) ([]ReservationHistory, error) {
	if err := page.validate(); err != nil {
		return nil, fmt.Errorf("顧客 %s の予約履歴: %w", customer, err)
	}
	rows, err := queries(ctx, q.pool).ListCustomerHistory(ctx, sqlcgen.ListCustomerHistoryParams{
		CustomerCode: customer,
		Limit:        int32(page.Limit),
		Offset:       int32(page.Offset),
	})
	if err != nil {
		return nil, fmt.Errorf("顧客 %s の予約履歴: %w", customer, err)
	}
	return listCustomerHistoryRowsToReservationHistories(rows), nil
}

// CountByCustomer は、顧客 customer の予約の総数を返す。ListByCustomer と同じ WHERE で数える。
func (q *ReservationHistoryQuery) CountByCustomer(ctx context.Context, customer string) (int, error) {
	n, err := queries(ctx, q.pool).CountCustomerReservations(ctx, customer)
	if err != nil {
		return 0, fmt.Errorf("顧客 %s の予約件数: %w", customer, err)
	}
	return int(n), nil
}
```

sqlc は `LIMIT $2 OFFSET $3` を `Limit int32` / `Offset int32` に、`count(*)` を `int64` に生成する。`Page` の `int` はここで `int32` へ、`int64` は `int` へ変換し、DTO とポートに sqlc 由来の幅を出さない。

## 7. エラー

`query` package の sentinel。拒む理由 1 つに 1 つ、日本語・句点なし・何が拒まれたか。

```go
package query

import "errors"

var (
	ErrNotFound            = errors.New("読み取り対象が見つからない")
	ErrDayHasClock         = errors.New("時刻を含む日付では読み取れない")
	ErrPageLimitOutOfRange = errors.New("取得件数が 1 件から上限までの範囲にない")
	ErrPageOffsetNegative  = errors.New("取得開始位置が負")
)
```

| 出所 | 翻訳先 | 境界での扱い |
|---|---|---|
| `:one` の `pgx.ErrNoRows` | `query.ErrNotFound` | NotFound |
| 引数の形（日付・範囲） | `ErrDayHasClock` / `ErrPageLimitOutOfRange` / `ErrPageOffsetNegative` | InvalidArgument |
| 上のどれでもない（接続断・SQL の失敗） | 翻訳しない。文脈を足して返す | Internal |

DB の制約違反は読み取りでは起きない。ドメインの sentinel を返すことはない（ドメインを import しないので返せない）。境界の翻訳表にどう載せるかは、エラーの規約と入口の規約が決める。

## 8. command の材料を読む query service

command（仮押さえ）が集約の外で守る不変条件や、VO の導出に使う材料も、同じ形の query service が読む。違いは呼ばれる場所が command の `Run` の中で、§3 の `queries(ctx, pool)` が ctx の tx を選ぶことだけである。判定（重なり・資格）はしない。材料を行のまま DTO か `[]time.Time` に写して返す。常駐 worker が「どの予約に command を掛けるか」を選ぶ材料（期限が到来した仮押さえの予約番号）も同じ形で、`[]string` に写して返す。

`rdb/query/active_reservation_read.sql`。現在有効な予約の利用枠は `room_booking_claims`（取消・期限切れで行が消えるので、残っている行が有効な予約）。重なりは半開区間 `[starts_at, ends_at)` で、`ends_at > 開始 AND starts_at < 終了`。日単位ではなく、渡された利用枠と重なる行だけを返す:

```sql
-- name: ListActiveOverlappingClaims :many
SELECT reservation_id, starts_at, ends_at
FROM room_booking_claims
WHERE room_code = $1
  AND ends_at > sqlc.arg(slot_starts_at)
  AND starts_at < sqlc.arg(slot_ends_at)
ORDER BY starts_at, reservation_id;
```

`rdb/query/no_show_read.sql`。無断不利用の時刻は、基底イベントに `reservation_no_show_recorded_events`（資料に無い仮定の 9 表目。無断不利用は資料の範囲外）を JOIN した `occurred_at`。直近 30 日への絞り込みは資料の数で、ドメインの `NewEligibility` が行うので SQL に書かない:

```sql
-- name: ListCustomerNoShowAt :many
SELECT e.occurred_at
FROM reservation_base_events e
JOIN reservation_no_show_recorded_events n ON n.base_event_id = e.id
JOIN reservations r ON r.reservation_id = e.reservation_id
WHERE r.customer_code = $1
ORDER BY e.occurred_at, e.id;
```

`rdb/query/due_hold_read.sql`。期限が到来した仮押さえは `tentative_hold_deadlines`（確定・取消・期限切れで行が消えるので、残っている行が仮押さえ中）の `expires_at` が判定時刻以下の行。同時刻は到来（`HasArrived` と同じ閉区間）で、`<=` に書く。期限が到来したかの判定は集約（`Expire`）が行うので、ここでは候補を選ぶだけ:

```sql
-- name: ListDueHoldIDs :many
SELECT reservation_id
FROM tentative_hold_deadlines
WHERE expires_at <= $1
ORDER BY expires_at, reservation_id;
```

```go
package query

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/rdb/sqlcgen"
)

type ActiveReservationQuery struct{ pool *pgxpool.Pool }

func NewActiveReservationQuery(pool *pgxpool.Pool) *ActiveReservationQuery {
	return &ActiveReservationQuery{pool: pool}
}

// ListActiveOverlapping は、会議室 roomCode で [startsAt, endsAt) と重なる現在有効な予約の利用枠を開始時刻順に返す。
// 重なるか（半開区間・隣接は重ならない）の判定は SQL の条件で行い、呼び手はドメインの Overlaps で確かめ直す。
func (q *ActiveReservationQuery) ListActiveOverlapping(ctx context.Context, roomCode string, startsAt, endsAt time.Time) ([]ActiveSlot, error) {
	rows, err := queries(ctx, q.pool).ListActiveOverlappingClaims(ctx, sqlcgen.ListActiveOverlappingClaimsParams{
		RoomCode:     roomCode,
		SlotStartsAt: startsAt,
		SlotEndsAt:   endsAt,
	})
	if err != nil {
		return nil, fmt.Errorf("会議室 %s の有効な予約の利用枠: %w", roomCode, err)
	}
	return listActiveOverlappingClaimsRowsToActiveSlots(rows), nil
}

type NoShowQuery struct{ pool *pgxpool.Pool }

func NewNoShowQuery(pool *pgxpool.Pool) *NoShowQuery {
	return &NoShowQuery{pool: pool}
}

// ListNoShowAt は、顧客 customerCode の予約で記録された無断不利用の時刻を古い順に返す。無ければ nil。
func (q *NoShowQuery) ListNoShowAt(ctx context.Context, customerCode string) ([]time.Time, error) {
	rows, err := queries(ctx, q.pool).ListCustomerNoShowAt(ctx, customerCode)
	if err != nil {
		return nil, fmt.Errorf("顧客 %s の無断不利用の時刻: %w", customerCode, err)
	}
	return listCustomerNoShowAtRowsToTimes(rows), nil
}

type DueHoldQuery struct{ pool *pgxpool.Pool }

func NewDueHoldQuery(pool *pgxpool.Pool) *DueHoldQuery {
	return &DueHoldQuery{pool: pool}
}

// ListDueHoldIDs は、判定時刻 at に期限が到来している仮押さえの予約番号を期限の古い順に返す。無ければ nil。
// 呼び手（常駐 worker）は 1 件ごとに期限切れの command を呼び、到来したかの判定は集約が確かめ直す。
func (q *DueHoldQuery) ListDueHoldIDs(ctx context.Context, at time.Time) ([]string, error) {
	rows, err := queries(ctx, q.pool).ListDueHoldIDs(ctx, at)
	if err != nil {
		return nil, fmt.Errorf("期限到来の仮押さえの予約番号: %w", err)
	}
	return rows, nil
}
```

`ListDueHoldIDs` は 1 列（`reservation_id`）なので、sqlc は `Row` 型を作らず `[]string` を返す。UTC 化も幅の変換も無いので、行 → DTO の関数を置かず、生成メソッドの結果をそのまま返す。

`query/active_reservation_marshaller.go` / `query/no_show_marshaller.go`:

```go
package query

import (
	"time"

	"example.com/roomflow/rdb/sqlcgen"
)

func listActiveOverlappingClaimsRowsToActiveSlots(rows []sqlcgen.ListActiveOverlappingClaimsRow) []ActiveSlot {
	var slots []ActiveSlot // 0 件は nil のまま返す
	for _, row := range rows {
		slots = append(slots, listActiveOverlappingClaimsRowToActiveSlot(row))
	}
	return slots
}

func listActiveOverlappingClaimsRowToActiveSlot(row sqlcgen.ListActiveOverlappingClaimsRow) ActiveSlot {
	return ActiveSlot{
		ReservationID: row.ReservationID,
		StartsAt:      row.StartsAt.UTC(),
		EndsAt:        row.EndsAt.UTC(),
	}
}

// listCustomerNoShowAtRowsToTimes は 1 列の行を UTC に揃える。sqlc は列が 1 つなら Row 型を作らず []time.Time を返す。
func listCustomerNoShowAtRowsToTimes(rows []time.Time) []time.Time {
	var out []time.Time // 0 件は nil のまま返す
	for _, t := range rows {
		out = append(out, t.UTC())
	}
	return out
}
```

| 規則 | 理由 |
|---|---|
| 重なりの条件は SQL に書き、日単位に丸めない | 「その日の予約を全部読んで Go で重なりを探す」は Go 側の絞り込みで、日をまたぐ枠を落とす。SQL が渡された枠と重なる行だけを返す |
| 返す行は材料だけ（識別子と利用枠）。`status` や期限を足さない | 呼び手（command）が要るのは重なりの判定に渡す利用枠だけ。表示のための列を混ぜると `AvailableSlot` と役割が重なる |
| 30 日・3 回のような資料の数を SQL に書かない | 数の置き場はドメイン（`NewEligibility`）1 か所。SQL に写すと 2 か所になる |
| 引数の検査は無い | `startsAt < endsAt` は利用枠の生成の条件で、command が `NewTimeSlot` で確かめてから呼ぶ |
| 期限到来の候補は `tentative_hold_deadlines` の `expires_at <= 判定時刻` で選び、`reservations.status` を見ない | 仮押さえ中かは期限行の有無で分かる。判定時刻は呼び手（worker）が 1 サイクル 1 回読んで渡し、SQL に `now()` を書かない |
