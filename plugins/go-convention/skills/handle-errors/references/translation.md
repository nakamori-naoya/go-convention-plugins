# 層ごとの翻訳

**翻訳は 2 段だけ。永続化層（リポジトリ・query service）が外部型（`*pgconn.PgError`・`pgx.ErrNoRows`・0 行）を sentinel へ、最外の interceptor が sentinel を `errors.Is` の対応表で `connect.Code` へ写す。** 間の層（usecase・handler 本体）は文脈を足すか素通しするだけで、分類しない。

## 1. 層ごとの表

| 層 | 受け取る error | 返す error | 翻訳するか |
|---|---|---|---|
| ドメイン（`reservation`） | なし | sentinel をそのまま | しない |
| リポジトリ（`rdb`） | pgx / pgconn の error、0 行 | DB 制約違反 → ドメイン sentinel。0 行 → `rdb.ErrNotFound`。楽観ロックの 0 行 → `rdb.ErrConflict`。それ以外 → 文脈を足してそのまま | **する**（外部型 → sentinel） |
| query service（`query`） | pgx の error、0 行、引数の形 | 0 行 → `query.ErrNotFound`。日付に時刻がある・件数が範囲外・開始位置が負 → `query.ErrDayHasClock` / `ErrPageLimitOutOfRange` / `ErrPageOffsetNegative`。それ以外 → 文脈を足してそのまま | **する**（外部型 → sentinel） |
| usecase | ドメイン sentinel、永続化層の sentinel、包まれた外部 error | 文脈を足したもの | しない。分類しない |
| handler 本体 | usecase の error、要求の欠け | usecase の error はそのまま `return nil, err`。要求の欠けは公開 sentinel（`handler.ErrStartsAtRequired` 等）をそのまま返す | しない。`connect.NewError` を書かない |
| interceptor（`Logging`） | 上のすべて | `*connect.Error` | **する**（sentinel → `connect.Code`） |

翻訳を 2 段に閉じると、`pgconn` を import するのは `rdb` と `query` だけ、`connect` を import するのは `handler` だけになる。usecase に外部型の名前が現れたら翻訳が漏れている。

## 2. ドメイン: 翻訳しない

sentinel をそのまま返す（[sentinels.md](sentinels.md) §2、[wrapping.md](wrapping.md) §1）。ドメインは「見つからない」も「競合した」も知らない。`AsTentative` が返すのは状態違いの sentinel であって、存在しない予約の話ではない。存在しない予約は `FindByID` の時点でリポジトリが `ErrNotFound` を返し、ドメインの絞り込みまで届かない。

## 3. リポジトリ: 外部型 → sentinel

`rdb/errors.go`:

```go
package rdb

import "errors"

// リポジトリ層の sentinel。永続化の都合による拒否で、資料の「拒む理由」には無い。
// rdb は複数の集約のリポジトリを持つので、文言に集約名を入れない。
var (
	ErrNotFound      = errors.New("対象が見つからない")              // FindByID で 0 行
	ErrConflict      = errors.New("対象が別の操作で更新された")          // 楽観ロックの 0 行、reservation_base_events の一意制約違反
	ErrNoTransaction = errors.New("トランザクションの外ではリポジトリを呼べない") // ctx に tx が無い。呼ぶ側の誤り
)
```

| 外部の事象 | 写す先 | 理由 |
|---|---|---|
| 集約の current 行（`GetReservation`）の `pgx.ErrNoRows` | `ErrNotFound` | 「無い」はリポジトリの語彙。ドメインに「見つからない」という拒む理由は無い |
| `UpdateReservationCurrent`（`WHERE reservation_id = $1 AND current_version = expected_version`）が 0 行 | `ErrConflict` | 別の操作が先に版を進めた。呼ぶ側は読み直してやり直す |
| `reservation_base_events (reservation_id, version)` の名前付き一意制約 `reservation_base_events_reservation_id_version_uniq` の違反（`23505`） | `ErrConflict` | 同じ版のイベントを二つ積もうとした。楽観ロックと同じ意味 |
| `room_booking_claims` の名前付き排他制約 `room_booking_claims_no_overlap` の違反（`23P01`） | `reservation.ErrOverlappingSlot` | 集約の外で守る不変条件が DB で破れた。生成を呼ぶ側の事前確認と同じ拒否理由にする（[sentinels.md](sentinels.md) §5） |
| current 行が仮押さえなのに `tentative_hold_deadlines` が 0 行 | 翻訳しない。文脈を足してそのまま | データ破損。`ErrNotFound` にすると usecase が「無い」として扱う |
| `tx.From(ctx)` が `false` | `ErrNoTransaction` | 呼ぶ側の誤り。対応表に載せず `Internal` |
| 上のどれでもない pgx / pgconn の error | 文脈を足してそのまま | 接続断・構文・型の不一致は業務の拒否ではない。`Internal` として境界が記録する |

`rdb/reservation_repository.go`（`FindByID` / `ApplyHeld` / `ApplyConfirmed` の翻訳に関わる行だけ。marshaller と残りのテーブルへの書き込みは省く。`translateConstraint` は `rdb/errors.go` にあり、この後に示す）:

```go
package rdb

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"example.com/roomflow/rdb/sqlcgen"
	"example.com/roomflow/reservation"
	"example.com/roomflow/tx"
)

// reservations.status の値。
const (
	statusTentative = "tentative"
	statusConfirmed = "confirmed"
)

type ReservationRepository struct{}

func NewReservationRepository() *ReservationRepository { return &ReservationRepository{} }

// queries は ctx の tx から sqlc の Queries を作る。tx が無ければ ErrNoTransaction。
func queries(ctx context.Context) (*sqlcgen.Queries, error) {
	t, ok := tx.From(ctx)
	if !ok {
		return nil, ErrNoTransaction
	}
	return sqlcgen.New(t), nil
}

func (r *ReservationRepository) FindByID(ctx context.Context, id reservation.ID) (reservation.Reservation, error) {
	q, err := queries(ctx)
	if err != nil {
		return nil, err
	}
	row, err := q.GetReservation(ctx, id.Value())
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("予約 %s の取得: %w", id.Value(), ErrNotFound)
		}
		return nil, fmt.Errorf("予約 %s の取得: %w", id.Value(), err)
	}
	// 仮押さえ期限は current 行が仮押さえのときだけ読む。そのとき 0 行ならデータ破損なので、ErrNoRows を「無い」に読み替えない
	var deadline *sqlcgen.TentativeHoldDeadline
	if row.Status == statusTentative {
		d, err := q.GetTentativeHoldDeadline(ctx, id.Value())
		if err != nil {
			return nil, fmt.Errorf("予約 %s の仮押さえ期限の取得: %w", id.Value(), err)
		}
		deadline = &d
	}
	// 無断不利用の記録は確定済みのときだけ読む。無いことが正常なので :many で読み、0 行を「起きていない」として渡す
	var noShowAt []time.Time
	if row.Status == statusConfirmed {
		noShowAt, err = q.ListReservationNoShowRecordedAt(ctx, id.Value())
		if err != nil {
			return nil, fmt.Errorf("予約 %s の無断不利用の記録の取得: %w", id.Value(), err)
		}
	}
	res, err := reservationRowToReservation(row, deadline, noShowAt)
	if err != nil {
		return nil, fmt.Errorf("予約 %s の復元: %w", id.Value(), err)
	}
	return res, nil
}

func (r *ReservationRepository) ApplyHeld(ctx context.Context, evt reservation.Held) error {
	q, err := queries(ctx)
	if err != nil {
		return err
	}
	id := evt.ReservationID().Value()
	if err := q.InsertReservation(ctx, heldToInsertReservationParams(evt)); err != nil {
		return fmt.Errorf("予約 %s の仮押さえの保存: %w", id, translateConstraint(err))
	}
	if err := q.InsertRoomBookingClaim(ctx, heldToInsertRoomBookingClaimParams(evt)); err != nil {
		return fmt.Errorf("予約 %s の占有の保存: %w", id, translateConstraint(err))
	}
	// 以下 tentative_hold_deadlines / reservation_base_events / reservation_tentative_created_events も同じ形
	return nil
}

func (r *ReservationRepository) ApplyConfirmed(ctx context.Context, evt reservation.ConfirmedEvent) error {
	q, err := queries(ctx)
	if err != nil {
		return err
	}
	id := evt.ReservationID().Value()
	n, err := q.UpdateReservationCurrent(ctx, sqlcgen.UpdateReservationCurrentParams{
		ReservationID:   id,
		Status:          statusConfirmed,
		CurrentVersion:  int32(evt.Version().Value()),
		UpdatedAt:       evt.OccurredAt(),
		ExpectedVersion: int32(evt.Version().Value() - 1),
	})
	if err != nil {
		return fmt.Errorf("予約 %s の確定の保存: %w", id, translateConstraint(err))
	}
	if n == 0 {
		return fmt.Errorf("予約 %s の確定の保存: %w", id, ErrConflict)
	}
	// 以下 tentative_hold_deadlines の DELETE / reservation_base_events / reservation_confirmed_events の INSERT
	return nil
}
```

`rdb/errors.go`（§1 の sentinel と同じファイル。翻訳表は `rdb` に 1 つ）:

```go
package rdb

import (
	"errors"

	"github.com/jackc/pgx/v5/pgconn"

	"example.com/roomflow/reservation"
)

// PostgreSQL の SQLSTATE。制約違反（クラス 23）だけを見る。
const (
	sqlstateUniqueViolation    = "23505"
	sqlstateExclusionViolation = "23P01"
)

// translateConstraint は PostgreSQL の制約違反を sentinel へ写す。写せない error はそのまま返す。
// 翻訳したら元の *pgconn.PgError は連鎖に残さない。どの制約で拒まれたかは sentinel が語る。
func translateConstraint(err error) error {
	pgErr, ok := errors.AsType[*pgconn.PgError](err)
	if !ok {
		return err
	}
	switch pgErr.Code {
	case sqlstateExclusionViolation:
		if pgErr.ConstraintName == "room_booking_claims_no_overlap" {
			return reservation.ErrOverlappingSlot
		}
	case sqlstateUniqueViolation:
		if pgErr.ConstraintName == "reservation_base_events_reservation_id_version_uniq" {
			return ErrConflict
		}
	}
	return err
}
```

| 規則 | 理由 |
|---|---|
| 翻訳表は制約名で引く（`ConstraintName`）。SQLSTATE だけで引かない。翻訳する制約は DDL で名前を付け、自動生成名（`..._key` / `..._excl`）に依存しない | 同じ `23505` でも、主キー重複（呼ぶ側の誤り → `Internal`）と version の重複（競合 → `ErrConflict`）は意味が違う。自動生成名は DDL の書き方で変わる |
| 翻訳表に無い制約違反はそのまま返す | 知らない制約を勝手に業務の拒否にしない。`Internal` として記録され、表に載せるかを人が決める |
| 翻訳したら元の外部 error を捨てる | `%w` は 1 つ。sentinel が拒否理由を語り、制約名は翻訳表に書いてある |
| `pgx.ErrNoRows` を `ErrNotFound` にするのは集約の current 行（`GetReservation`）だけ。従属行は current 行の状態から「あるはず」のときだけ読み、その 0 行は翻訳せずそのまま返す | 従属行の 0 行はデータ破損で、「無い」ではない。`ErrNotFound` にすると usecase が `NotFound` として扱う。無条件に読んで `ErrNoRows` を「無い」に読み替えるのは丸め（[wrapping.md](wrapping.md) §9） |
| `INSERT` / `UPDATE` / `DELETE` の error は `translateConstraint` に通す。`SELECT` には通さない | 制約違反は書き込みでしか起きない |
| marshaller（行 → ドメイン）の error は `ErrNotFound` にしない | 行はある。復元できないのは不正なデータか marshaller の誤りで、`Internal` |

## 4. usecase: 文脈を足すだけ

[wrapping.md](wrapping.md) §1 の `Execute`。usecase は `errors.Is` で分岐する必要があるときだけ判定し（無ければ作る等）、それ以外は包んで返す。`connect.Code` を選ばない。「この error は利用者に見せてよいか」を判断しない。どちらも境界の対応表が決める。

## 5. interceptor: sentinel → `connect.Code`

対応表は `handler/error_table.go` の `codeTable` 1 か所で、当てる関数は `toConnectError`。呼ぶのは最外の interceptor `Logging`（`handler/logging_interceptor.go`。Scope の生成・recover・RPC 1 回につきログ 1 行もここで、その形はログの規約が持つ）だけである。handler 本体は `connect.NewError` を書かず、usecase の error をそのまま返す。

`Logging` の中で `next` の error を受け取る行:

```go
			res, err = next(ctx, req)
			if err == nil {
				return res, nil
			}
			cerr := toConnectError(err)
			// ログはここで 1 回（ログの規約）。翻訳前の err を記録し、翻訳後の cerr を返す
			return nil, cerr
```

`handler/error_table.go`:

```go
package handler

import (
	"context"
	"errors"

	"connectrpc.com/connect"

	"example.com/roomflow/query"
	"example.com/roomflow/rdb"
	"example.com/roomflow/reservation"
)

// codeTable は error を connect.Code へ写す唯一の対応表。上から順に errors.Is で引く。
var codeTable = []struct {
	err  error
	code connect.Code
}{
	// 本人でない
	{reservation.ErrNotOwner, connect.CodePermissionDenied},
	// 事前条件・状態違い・重なり: 今の状態では受け付けない
	{reservation.ErrHoldDeadlinePassed, connect.CodeFailedPrecondition},
	{reservation.ErrAlreadyConfirmed, connect.CodeFailedPrecondition},
	{reservation.ErrAlreadyCancelled, connect.CodeFailedPrecondition},
	{reservation.ErrAlreadyExpired, connect.CodeFailedPrecondition},
	{reservation.ErrSlotAlreadyStarted, connect.CodeFailedPrecondition},
	{reservation.ErrOverlappingSlot, connect.CodeFailedPrecondition},
	{reservation.ErrCustomerSuspended, connect.CodeFailedPrecondition},
	// 入力不正: 値オブジェクトの生成の条件、handler が検出した要求の欠け、query service の引数の形
	{reservation.ErrIDRequired, connect.CodeInvalidArgument},
	{reservation.ErrRoomCodeRequired, connect.CodeInvalidArgument},
	{reservation.ErrTimeSlotNotOrdered, connect.CodeInvalidArgument},
	{ErrStartsAtRequired, connect.CodeInvalidArgument},
	{ErrEndsAtRequired, connect.CodeInvalidArgument},
	{query.ErrDayHasClock, connect.CodeInvalidArgument},
	{query.ErrPageLimitOutOfRange, connect.CodeInvalidArgument},
	{query.ErrPageOffsetNegative, connect.CodeInvalidArgument},
	// 永続化
	{rdb.ErrNotFound, connect.CodeNotFound},
	{query.ErrNotFound, connect.CodeNotFound},
	{rdb.ErrConflict, connect.CodeAborted},
	// 呼び手の中断
	{context.Canceled, connect.CodeCanceled},
	{context.DeadlineExceeded, connect.CodeDeadlineExceeded},
}

// toConnectError は返った error を *connect.Error にする。表に無ければ Internal と固定文言（handler/errors.go の errInternal）。
func toConnectError(err error) *connect.Error {
	if cerr, ok := errors.AsType[*connect.Error](err); ok {
		return cerr // Auth が作った Unauthenticated など。二重に翻訳しない
	}
	for _, row := range codeTable {
		if errors.Is(err, row.err) {
			return connect.NewError(row.code, row.err)
		}
	}
	return connect.NewError(connect.CodeInternal, errInternal)
}
```

handler の sentinel（`handler/errors.go`）。要求に欠けがあるとき変換関数がそのまま返す公開 sentinel（`codeTable` が `InvalidArgument` に写す。テストが `require.ErrorIs` で指せるよう公開する）と、翻訳表に載せない非公開の 2 つ（組み立ての誤り `errNoCaller`、`Internal` の固定文言 `errInternal`）をここに置く。`error_table.go` には表と `toConnectError` だけを置く:

```go
package handler

import "errors"

// 要求の欠け。文言は利用者に見せる（連鎖の文脈は見せない）ので、何が欠けたかを日本語で書く。
var (
	ErrStartsAtRequired = errors.New("利用開始の無い仮押さえ要求は受け付けない")
	ErrEndsAtRequired   = errors.New("利用終了の無い仮押さえ要求は受け付けない")
)

// 組み立ての誤り。翻訳表に載せず Internal にする。
var errNoCaller = errors.New("呼び手の主体が ctx に無い")

// errInternal は翻訳表に無い error に返す唯一の公開文言。内部の連鎖は出さない。
var errInternal = errors.New("内部エラーが発生した")
```

| 規則 | 理由 |
|---|---|
| 表は 1 か所。handler 本体にも変換関数にも `connect.NewError` を書かない | 同じ sentinel が RPC ごとに違う Code になる事故を無くす。表を読めば公開 API のエラー契約が全部分かる |
| 公開する文言は sentinel の文言だけ（`connect.NewError(code, row.err)`）。包んだ文脈（`予約 R-0101 の確定: ...`）は出さない | 文脈は運用者向けで、ログが持つ。利用者は自分が何を求めたか知っている |
| 表に無い error は `Internal` で固定文言「内部エラーが発生した」。内部の連鎖・外部ライブラリの文言を出さない | SQL や接続先の情報を外に出さない。内部の失敗を利用者が直せる形にはできない |
| `ErrEligibilityMismatch` / `ErrNoReservation` / `ErrVersionNotPositive` / `rdb.ErrNoTransaction` / `errNoCaller` は表に載せない | 利用者の入力では起きない。usecase の取り違え・組み立ての誤り・保存済みデータの破損なので `Internal` として記録し、直すのは実装者 |
| `ErrCustomerIDRequired` は表に載せない | 予約者は要求の本文ではなく認証の主体から来る。空なら `callerFrom` が `errNoCaller` で先に止めるので、ここに届くのは誤り |
| `*connect.Error` は素通し | 認証の interceptor（`Auth`）は `Unauthenticated` を自分で作る。二重に翻訳しない |
| 表は `errors.Is` で上から順に引く | 型付きエラー（[sentinels.md](sentinels.md) §6）も `Is` で sentinel に答えるので、表に型を足さなくてよい |

### Code の選び方

| 拒否 | Code | 利用者ができること |
|---|---|---|
| 本人でない（`ErrNotOwner`） | `PermissionDenied` | 自分の予約を選び直す |
| 事前条件・状態違い・重なり（期限以降・確定済み・取消済み・期限切れ・利用開始以降・重なる利用枠・停止中） | `FailedPrecondition` | 状態が変わるまで、または別の利用枠で申し込み直す |
| 無い（`rdb.ErrNotFound` / `query.ErrNotFound`） | `NotFound` | 予約番号・会議室コードを確かめる |
| 競合（`rdb.ErrConflict`） | `Aborted` | 読み直して同じ操作をやり直す |
| 入力不正（値オブジェクトの生成の条件・要求の欠け・query service の引数の形） | `InvalidArgument` | 入力を直す |
| それ以外 | `Internal` | 何もできない。実装者が直す |

`AlreadyExists` は作らない。予約番号は usecase が採番するので、重複は利用者の入力ではなく実装の誤りである。`Unavailable` / `ResourceExhausted` は接続・上限の話で、この規約の sentinel には無い。要る事象が出たら表に 1 行足す。

## 6. 表の変更手順

sentinel を 1 つ足したら、対応表に行を足すか、`Internal` でよいと決めて足さないかを、そのときに決める。決めずに残すと、業務の拒否が `Internal` として記録され、利用者は「内部エラー」しか見ない。

| 足す sentinel | 決めること |
|---|---|
| 資料の「拒む理由」から | ほぼ `FailedPrecondition` か `PermissionDenied`。表に足す |
| 値オブジェクトの生成の条件、要求の欠け、query service の引数の形から | `InvalidArgument`。表に足す。ただし利用者の入力から来ない値（認証の主体・復元した版）の生成の条件は足さない |
| 呼ぶ側の誤り（取り違え・tx 無し） | 足さない。`Internal` |
| リポジトリの新しい制約違反 | どの sentinel へ写すかを §3 の `translateConstraint` に足し、その sentinel の行が表にあるか見る |
