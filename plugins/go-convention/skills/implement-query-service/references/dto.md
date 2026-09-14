# DTO と行 → DTO

**DTO は、読み取りモデルを公開フィールドの struct で表した「見せるための形」である。** 業務語で名付け、標準の型だけを持ち、テーブルの行から純粋関数で作る。ドメインの型・sqlc の型・proto の型を含まない。

## 1. 形

| 項目 | 規則 | 理由 |
|---|---|---|
| 型 | 公開フィールドの struct。メソッドを持たない（getter・`String()`・検証を書かない） | データであって値オブジェクトではない。不変条件を持たず、詰めた値をそのまま見せる |
| 名前 | 業務語（`RoomAvailability` / `AvailableSlot` / `ReservationHistory`）。`DTO` / `Model` / `Row` / `Response` の接尾辞を付けない | 読み取りモデルの名前は業務の問い（空き状況・予約履歴）に対する答えの名前 |
| 識別子 | `string`（`ReservationID string` / `RoomCode string`） | VO の `ID` 型を使わない。ドメインを import しない |
| 時刻 | `time.Time`（UTC）。行から写すときに `.UTC()` を通す | `==` と `Equal` の両方で比べられる。時差はハンドラより外の関心 |
| 金額・数量・件数 | 明示の型（`int` / `int64` / 小数は `decimal` 等、プロジェクトの規約が決めた型）。sqlc の `int32` は DTO に出さない | DTO の幅は業務が決め、DB の物理型に引きずられない |
| 語彙（状態・種別） | `string` に、データモデル資料の値域を定数で持つ | DB の語彙と DTO の語彙を 1 つにし、翻訳表を 2 つ持たない。proto の enum への写しは handler |
| 入れ子 | 親子は親 struct のスライスフィールド（`Slots []AvailableSlot`） | 1 つの問いに 1 つの DTO で答える。呼び手が 2 つの結果を突き合わせない |
| proto | 返さない。DTO → proto の変換は handler が持つ | query service は入口プロトコルを知らない |
| ポインタ・`pgtype`・`sql.Null*` | 持たない | 「無い」は §3 の形で表す |

## 2. 題材の DTO

```go
package query

import "time"

// reservations.status の値域。データモデル資料の語彙をそのまま持つ。
const (
	StatusTentative = "tentative"
	StatusConfirmed = "confirmed"
	StatusCancelled = "cancelled"
	StatusExpired   = "expired"
)

// RoomAvailability は、ある会議室のある日の空き状況。Slots は占有中の利用枠を開始時刻順に並べたもので、
// その隙間が空いている時間帯である。占有が無ければ Slots は nil。
type RoomAvailability struct {
	RoomCode string
	Slots    []AvailableSlot
}

// AvailableSlot は、空き状況を構成する占有中の利用枠 1 つ。
// HoldExpiresAt は仮押さえのときだけあり、有無は HasHoldExpiresAt で見る。
type AvailableSlot struct {
	ReservationID    string
	StartsAt         time.Time
	EndsAt           time.Time
	Status           string // StatusTentative か StatusConfirmed（占有中の枠は取消済み・期限切れにならない）
	HoldExpiresAt    time.Time
	HasHoldExpiresAt bool
}

// ActiveSlot は、現在有効な予約（仮押さえ・確定）が占有している利用枠 1 つ。
// 仮押さえの command が「同じ会議室の重なる利用枠に有効な予約が無い」を確かめる材料で、重なりの判定はドメインが行う。
type ActiveSlot struct {
	ReservationID string
	StartsAt      time.Time
	EndsAt        time.Time
}

// ReservationHistory は、予約 1 件の現在の姿と、起きた出来事の並び。
type ReservationHistory struct {
	ReservationID string
	RoomCode      string
	StartsAt      time.Time
	EndsAt        time.Time
	Status        string
	Events        []HistoryEvent
}

// HistoryEvent は、予約に起きた出来事 1 つ（基底イベントの行）。
type HistoryEvent struct {
	Version    int
	EventType  string
	ActorCode  string
	OccurredAt time.Time
}
```

`Status` の値域は 4 つ全部を定数にする。`AvailableSlot.Status` に現れるのは 2 つだが、`ReservationHistory.Status` には 4 つが現れ、語彙は DTO ごとに分けない。

`ActiveSlot` は表示ではなく command の材料のための DTO で、形は同じ規則に従う（公開フィールド・`string` と `time.Time`・メソッド無し）。`AvailableSlot` と列が似ていても、問い（空き状況を見せる／重なりを確かめる）が違うので DTO を分け、片方にフィールドを足して兼ねさせない。「顧客の予約で起きた無断不利用の時刻」のように値が 1 列だけの材料は、DTO を作らず `[]time.Time` で返す。「期限が到来した仮押さえの予約番号」も同じで、`[]string` は DTO を作らない。

## 3. 「無い」の表し方

「無い」を既定の値で塗りつぶさない。形は 3 つで、それ以外を作らない。

| 何が無いか | 形 | 例 |
|---|---|---|
| NULL 許可列の値 | 値と有無の対 `{X} T` + `Has{X} bool`。行 → DTO では `(T, bool)` を返す関数で写す | `HoldExpiresAt time.Time` + `HasHoldExpiresAt bool` |
| 一覧の要素 | nil スライスのまま返す。`[]T{}` を作らない | `Slots: nil`（`var slots []AvailableSlot` に append しなかった結果） |
| `:one` の対象 | `query.ErrNotFound` を返す。ゼロ値の DTO と `nil` error の組で返さない | `(ReservationSummary{}, ErrNotFound)` |

- 対にする理由: ポインタは nil 参照の危険と別名参照を持ち込み、ゼロ時刻を「無い」に使うと 0001-01-01 が本物の値と区別できない。`Has{X}` が偽のとき `{X}` はゼロ値で、読まない
- nil スライスにする理由: 0 件と「無い」を DTO で区別しない。区別が要る問い（会議室が存在するか）は読み取りモデルの問いではなく、別のテーブルを読む別の query になる。JSON や proto で `[]` が要るなら handler が写す
- 有無を `Status` から推測しない: `HasHoldExpiresAt` は `Status == StatusTentative` から導けるが、行にある事実（`expires_at` が NULL でない）をそのまま写す。導出は業務判断で、ドメインの関心

## 4. 行 → DTO の関数

sqlc の行を DTO に写す関数は、query 型と同じ package の**純粋関数**である。引数の行と、呼び手が渡した値以外を読まず、DB にもドメインにも触らない。

| 項目 | 規則 |
|---|---|
| 置き場 | `query/{name}_marshaller.go`。query 型のメソッドにしない（`pool` を読めてしまう） |
| 名前 | `{Row}To{DTO}`。`{Row}` は sqlc の行型の名前を小文字始まりにしたもの。1 行 → 1 DTO は `listRoomSlotsForDayRowToAvailableSlot`、行の並び → 1 DTO は `listRoomSlotsForDayRowsToRoomAvailability`、行の並び → DTO の並びは `listCustomerHistoryRowsToReservationHistories` |
| 引数 | 行（または行のスライス）と、行に無いが DTO に要る値（`room`）。ctx・pool・時計を渡さない |
| 返り値 | DTO 1 つ。error を返さない（行は DB が型を保証していて、写すだけなら失敗しない） |
| NULL 列 | `pgtype.Timestamptz` 等を `(T, bool)` にする関数（`timestamptzToTime`）を通し、DTO の対に入れる |
| 時刻 | `time.Time` の列も `.UTC()` を通す（pgx は接続のタイムゾーンで返すことがある） |
| 幅 | sqlc の `int32` / `int64` は DTO の型（`int`）へここで変換する |
| 分岐 | NULL の有無だけ。行の値で DTO の形を変えない（形が違うなら DTO を分け、query も分ける） |

```go
package query

import (
	"time"

	"github.com/jackc/pgx/v5/pgtype"

	"example.com/roomflow/rdb/sqlcgen"
)

// listRoomSlotsForDayRowsToRoomAvailability は、会議室 room の占有中の枠の行を空き状況 1 つに写す。
func listRoomSlotsForDayRowsToRoomAvailability(room string, rows []sqlcgen.ListRoomSlotsForDayRow) RoomAvailability {
	var slots []AvailableSlot // 0 件は nil のまま返す
	for _, row := range rows {
		slots = append(slots, listRoomSlotsForDayRowToAvailableSlot(row))
	}
	return RoomAvailability{RoomCode: room, Slots: slots}
}

func listRoomSlotsForDayRowToAvailableSlot(row sqlcgen.ListRoomSlotsForDayRow) AvailableSlot {
	holdExpiresAt, hasHoldExpiresAt := timestamptzToTime(row.ExpiresAt)
	return AvailableSlot{
		ReservationID:    row.ReservationID,
		StartsAt:         row.StartsAt.UTC(),
		EndsAt:           row.EndsAt.UTC(),
		Status:           row.Status,
		HoldExpiresAt:    holdExpiresAt,
		HasHoldExpiresAt: hasHoldExpiresAt,
	}
}

// timestamptzToTime は NULL 許可の timestamptz 列を (T, bool) に写す。NULL は (ゼロ値, false)。
func timestamptzToTime(v pgtype.Timestamptz) (time.Time, bool) {
	if !v.Valid {
		return time.Time{}, false
	}
	return v.Time.UTC(), true
}
```

`RoomCode` は行に無い（`WHERE` の条件で固定されている）ので、呼び手が `room` を渡す。行から取れる値を引数で二重に渡さない。

## 5. 複数行 → 1 DTO のグルーピング

親 1 行に子が複数付く JOIN は、親の列が子の行数だけ繰り返される。親の識別子で畳み、初出の行で親を作り、各行で子を足す。`ORDER BY` が親 → 子の順に並べているので、親は連続して現れるが、畳み込みは順序に頼らず `seen` で親の位置を引く。

```go
package query

import "example.com/roomflow/rdb/sqlcgen"

// listCustomerHistoryRowsToReservationHistories は、予約 × 出来事の行を予約ごとに畳む。
// 行は予約の順に並んでいるが、畳み込みは seen で親の位置を引き、順序に頼らない。
func listCustomerHistoryRowsToReservationHistories(rows []sqlcgen.ListCustomerHistoryRow) []ReservationHistory {
	var out []ReservationHistory // 0 件は nil のまま返す
	seen := map[string]int{}     // reservation_id → out の添字
	for _, row := range rows {
		i, ok := seen[row.ReservationID]
		if !ok {
			i = len(out)
			seen[row.ReservationID] = i
			out = append(out, listCustomerHistoryRowToReservationHistory(row))
		}
		out[i].Events = append(out[i].Events, listCustomerHistoryRowToHistoryEvent(row))
	}
	return out
}

// listCustomerHistoryRowToReservationHistory は行の親の列だけを写す。Events は呼び手が足す。
func listCustomerHistoryRowToReservationHistory(row sqlcgen.ListCustomerHistoryRow) ReservationHistory {
	return ReservationHistory{
		ReservationID: row.ReservationID,
		RoomCode:      row.RoomCode,
		StartsAt:      row.StartsAt.UTC(),
		EndsAt:        row.EndsAt.UTC(),
		Status:        row.Status,
	}
}

// listCustomerHistoryRowToHistoryEvent は行の子の列だけを写す。
func listCustomerHistoryRowToHistoryEvent(row sqlcgen.ListCustomerHistoryRow) HistoryEvent {
	return HistoryEvent{
		Version:    int(row.Version),
		EventType:  row.EventType,
		ActorCode:  row.ActorCode,
		OccurredAt: row.OccurredAt.UTC(),
	}
}
```

| 規則 | 理由 |
|---|---|
| 親を作る関数と子を作る関数を分け、畳む関数はその 2 つを呼ぶだけ | 1 行 → 1 DTO の関数が単独で読める |
| 親の識別子は行の列（`reservation_id`）。複合キーなら struct をキーにする（文字列連結しない） | 連結は区切り文字の衝突で別の親を同一視する |
| 子が 0 件の親も出したいなら、`LEFT JOIN` にして子の列を NULL 許可で受け、`Has{X}` が偽の行では子を足さない | 親の一覧を別 query で読んで Go で突き合わせない |
| 子の順序は `ORDER BY` が決める。Go で並べ替えない | ソートは SQL の関心 |

## 6. handler へ渡すとき

DTO はここで終わり、proto への写しは handler が持つ。query service は `timestamppb` も `roomflowv1` も import しない。nil スライスは proto の repeated にそのまま渡せる。`Has{X}` が偽のフィールドは、handler が proto の optional を未設定にする。
