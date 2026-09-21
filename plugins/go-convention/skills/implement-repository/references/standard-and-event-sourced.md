# 2 つの永続化の型

**集約の永続化は「通常型」か「イベント型」のどちらか 1 つで、集約ごとに決まる。** 通常型は集約の次の状態を上書きし、イベント型はドメインイベントだけを受け取って追記し、current 行へ反映する。どちらも `FindByID` は和型を返す。

## 1. どちらを選ぶか

| データモデル資料 | 型 | 集約 |
|---|---|---|
| リソース系テーブルだけ | 通常型 | 版を持たない。`Restore*` に `Version` が無い |
| リソース系 ＋ イベント系（`{aggregate}_base_events` と種別ごとの詳細イベント表） | イベント型 | 版を持つ。ドメインイベントも版を持つ |

判断はデータモデル資料が決める。資料にイベント系テーブルがあるのに集約が版を持たない、または逆なら、この skill では解決できない（停止条件）。題材の「予約」はリソース系 3 表 ＋ イベント系 5 表なのでイベント型、比較用の「予約待ち」は通常型として書く。ドメインの `Repository` が `ApplyNoShowRecorded` を持つのに資料は無断不利用を範囲外にしているので、例は詳細イベント表 `reservation_no_show_recorded_events`（`id` / `base_event_id` だけ）を**資料に無い仮定の 9 表目**として置く。実装時は資料の改訂に従う。

## 2. interface の形

interface はドメイン層（集約と同じ package）に集約ごとに 1 つ定義済みである。ここでは形を確認するだけで、実装が interface を切らない。

```go
// package reservation（イベント型）
type Repository interface {
	FindByID(ctx context.Context, id ID) (Reservation, error)
	ApplyHeld(ctx context.Context, evt Held) error
	ApplyConfirmed(ctx context.Context, evt ConfirmedEvent) error
	ApplyCancelled(ctx context.Context, evt CancelledEvent) error
	ApplyExpired(ctx context.Context, evt ExpiredEvent) error
	ApplyNoShowRecorded(ctx context.Context, evt NoShowRecorded) error
}

// package waitlist（通常型）
type Repository interface {
	FindByID(ctx context.Context, id ID) (Waitlist, error)
	Create(ctx context.Context, w Waiting) error
	Update(ctx context.Context, w Waitlist) error
}
```

| 規則 | 理由 |
|---|---|
| `FindByID` は和型（`reservation.Reservation` / `waitlist.Waitlist`）を返す。`FindTentativeByID` のような状態指定取得を作らない | 状態の絞り込みは `AsTentative` 等がドメインで担い、違う状態の拒否は sentinel で返る。リポジトリが状態を選ぶと、拒む理由が 2 か所に分かれる |
| イベント型は集約そのものを絶対に受け取らない。`Update(ctx, agg)` / `Save(ctx, agg)` を作らない | 詳細イベント表の列はイベントの getter と 1:1 で、current 行もイベントから導ける。集約を受け取ると Next と Event の 2 つの一次データができ、どちらを書いたかが読めなくなる |
| 通常型は `Create` と `Update` を分ける | INSERT と UPDATE は失敗の意味が違う（重複 / 見つからない）。1 つの `Save` に畳むと、どちらが起きたかを翻訳できない |
| `Delete` / `Exists` / `List*` / `Count*` を足さない | 資料に削除の操作が無い限り `Delete` は無い。存在確認と一覧は読み取りモデルの関心で、集約を復元しない |
| 引数と返り値はドメインの型だけ。`pgx.Tx` / `*pgxpool.Pool` / `sqlcgen.*` を interface に出さない | usecase が DB を知らずに済む |

## 3. 通常型: 状態の上書き

`Create` は `INSERT`、`Update` は主キーで `UPDATE` し、行の全列を集約の現在の値で上書きする。版は無い。最後の書き込みが勝つ。同時更新を一方だけ通す必要が資料の「並行実行で必要な保証」にあるなら、それは DB 制約（一意・排他）で表すか、集約をイベント型にする。リポジトリが `SELECT ... FOR UPDATE` で守らない。

比較のための例。集約「予約待ち」は題材のデータモデル資料に無いので、テーブル `waitlists`（`waitlist_id` / `room_code` / `customer_code` / `starts_at` / `ends_at` / `accepted_at` / `status` / `ended_at`。`ended_at` だけ NULL 許可で、終了時刻。他は NOT NULL）1 表と、和型 `waitlist.Waitlist`（状態型 `Waiting` と、繰上げか取消かを `Promoted() bool`、終了時刻を `EndedAt() time.Time` で持つ `Ended`）を仮定する。

```go
package rdb

import (
	"context"
	"fmt"

	"example.com/roomflow/rdb/sqlcgen"
	"example.com/roomflow/waitlist"
)

type WaitlistRepository struct{}

func NewWaitlistRepository() *WaitlistRepository { return &WaitlistRepository{} }

func (r *WaitlistRepository) Create(ctx context.Context, w waitlist.Waiting) error {
	q, err := queries(ctx)
	if err != nil {
		return err
	}
	if err := q.InsertWaitlist(ctx, waitingToInsertWaitlistParams(w)); err != nil {
		return fmt.Errorf("予約待ち %s の作成: %w", w.ID().Value(), translateConstraint(err))
	}
	return nil
}

func (r *WaitlistRepository) Update(ctx context.Context, w waitlist.Waitlist) error {
	q, err := queries(ctx)
	if err != nil {
		return err
	}
	var params sqlcgen.UpdateWaitlistParams
	switch w := w.(type) {
	case waitlist.Waiting:
		params = waitingToUpdateWaitlistParams(w)
	case waitlist.Ended:
		params = endedToUpdateWaitlistParams(w)
	default:
		return fmt.Errorf("予約待ち %s の更新: 状態 %T は未知", w.ID().Value(), w)
	}
	rows, err := q.UpdateWaitlist(ctx, params)
	if err != nil {
		return fmt.Errorf("予約待ち %s の更新: %w", w.ID().Value(), translateConstraint(err))
	}
	if rows == 0 {
		return fmt.Errorf("予約待ち %s の更新: %w", w.ID().Value(), ErrNotFound)
	}
	return nil
}
```

- 和型の型スイッチはリポジトリに置き、状態ごとの marshaller（`waitingTo*` / `endedTo*`）を選ぶ。marshaller の中で型スイッチしない
- `default` は error を返す。sealed interface なので到達しないが、panic も黙殺もしない
- `UPDATE` が 0 行なら `ErrNotFound`。版が無いので競合ではなく「無い」である
- `queries(ctx)` と `translateConstraint` は [sqlc-and-tx.md](sqlc-and-tx.md) §4 と [error-translation.md](error-translation.md) §2

## 4. イベント型: イベントの追記と current 行への反映

`Apply{Event}` はドメインイベント 1 つを受け取り、次の順で書く。

| 順 | 書くもの | 内容 |
|---|---|---|
| 1 | リソース系の一次データ（`reservations`） | 初回イベント（`Held`）は INSERT。それ以外は楽観ロック付き UPDATE。0 行なら `ErrConflict` で即返す |
| 2 | リソース系の従属行（`room_booking_claims` / `tentative_hold_deadlines`） | 資料の「シナリオと記録の対応」の行どおりに INSERT / DELETE |
| 3 | 基底イベント（`reservation_base_events`） | INSERT。`version = evt.Version()`、`occurred_at = evt.OccurredAt()`。`RETURNING id` |
| 4 | 詳細イベント（`reservation_{種別}_events`） | INSERT。`base_event_id` は 3 の返り値。版は持たない |

UPDATE を先に置くのは、競合の検出を current 行の 0 行 1 点に集めるためである。イベントを先に入れると、競合は基底イベントの一意制約違反としても現れ、2 か所を見ることになる。

どのテーブルにどう書くかは、データモデル資料の「シナリオと記録の対応」の表がそのまま `Apply*` の仕様である。題材では:

| `Apply*` | `reservations` | `room_booking_claims` | `tentative_hold_deadlines` | `..._base_events` | 詳細イベント |
|---|---|---|---|---|---|
| `ApplyHeld` | INSERT（`tentative`, version 1） | INSERT | INSERT | INSERT | `tentative_created` |
| `ApplyConfirmed` | UPDATE（`confirmed`） | 変更なし | DELETE | INSERT | `confirmed` |
| `ApplyCancelled` | UPDATE（`cancelled`） | DELETE | DELETE | INSERT | `cancelled` |
| `ApplyExpired` | UPDATE（`expired`） | DELETE | DELETE | INSERT | `expired` |
| `ApplyNoShowRecorded` | UPDATE（`confirmed` のまま。版だけ進む） | 変更なし | 変更なし | INSERT | `no_show_recorded`（仮定の 9 表目） |

`ApplyNoShowRecorded` は状態を変えない操作のイベントだが、版は進むので current 行の UPDATE（楽観ロック）は省かない。無断不利用が起きた時刻は `reservations` に列を持たず（資料の流儀で全列 NOT NULL）、基底イベントの `occurred_at` が一次データで、`FindByID` が確定済みのときだけそれを読んで `RestoreConfirmed` に渡す。

### 版の扱い

| 用途 | 値 | 導出 |
|---|---|---|
| current 行の楽観ロック照合（更新前の版 n） | `expected_version` | `evt.Version().Value() - 1` |
| current 行の `current_version` と `base_events.version`（適用後の版 n+1） | `version` | `evt.Version().Value()` |

版はドメインイベントが持って来る（集約が復元時の版から `Next()` で採番済み）。リポジトリは `SELECT ... FOR UPDATE` で読み直さず、足しもしない。詳細イベント表に版を書かない（版は基底イベントに 1 か所）。

### `ApplyHeld`（初回: INSERT だけ）

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
)

type ReservationRepository struct{}

func NewReservationRepository() *ReservationRepository { return &ReservationRepository{} }

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
	if err := q.InsertTentativeHoldDeadline(ctx, heldToInsertTentativeHoldDeadlineParams(evt)); err != nil {
		return fmt.Errorf("予約 %s の仮押さえ期限の保存: %w", id, translateConstraint(err))
	}
	baseID, err := q.InsertReservationBaseEvent(ctx, eventToInsertReservationBaseEventParams(evt, eventTypeTentativeCreated, evt.Customer().Value()))
	if err != nil {
		return fmt.Errorf("予約 %s の基底イベントの保存: %w", id, translateConstraint(err))
	}
	if err := q.InsertReservationTentativeCreatedEvent(ctx, heldToInsertReservationTentativeCreatedEventParams(evt, baseID)); err != nil {
		return fmt.Errorf("予約 %s の仮押さえ成立イベントの保存: %w", id, translateConstraint(err))
	}
	return nil
}
```

`room_booking_claims` の INSERT が排他制約に弾かれると `translateConstraint` が `reservation.ErrOverlappingSlot` を返す。同じ空き枠への同時仮押さえ（資料 BDD-005）は、この 1 行で一方だけが通る。

### `ApplyConfirmed`（楽観ロック付き UPDATE → 従属行 → イベント）

```go
func (r *ReservationRepository) ApplyConfirmed(ctx context.Context, evt reservation.ConfirmedEvent) error {
	q, err := queries(ctx)
	if err != nil {
		return err
	}
	id := evt.ReservationID().Value()
	rows, err := q.UpdateReservationCurrent(ctx, eventToUpdateReservationCurrentParams(evt, statusConfirmed))
	if err != nil {
		return fmt.Errorf("予約 %s の確定の保存: %w", id, translateConstraint(err))
	}
	if rows == 0 {
		return fmt.Errorf("予約 %s の確定の保存: %w", id, ErrConflict)
	}
	if err := q.DeleteTentativeHoldDeadline(ctx, id); err != nil {
		return fmt.Errorf("予約 %s の仮押さえ期限の削除: %w", id, translateConstraint(err))
	}
	baseID, err := q.InsertReservationBaseEvent(ctx, eventToInsertReservationBaseEventParams(evt, eventTypeConfirmed, evt.By().Value()))
	if err != nil {
		return fmt.Errorf("予約 %s の基底イベントの保存: %w", id, translateConstraint(err))
	}
	if err := q.InsertReservationConfirmedEvent(ctx, baseID); err != nil {
		return fmt.Errorf("予約 %s の確定イベントの保存: %w", id, translateConstraint(err))
	}
	return nil
}
```

- `UpdateReservationCurrent` は `:execrows` で、`WHERE reservation_id = $1 AND current_version = expected_version` の更新行数を返す（[sqlc-and-tx.md](sqlc-and-tx.md) §2）
- 0 行は「版が進んでいた」であって「無い」ではない。usecase が同じ tx で `FindByID` してから `Apply*` を呼び、`reservations` の行は消えないので、0 行の原因は版の不一致に限られる
- UPDATE の error も `translateConstraint` に通す。書き込みはすべて制約に当たりうる（[error-translation.md](error-translation.md) §2）
- 基底イベントの `actor_code` はイベントの getter から出す（`ConfirmedEvent.By()` / `CancelledEvent.By()`。`Held` は `Customer()`）
- `ApplyCancelled` / `ApplyExpired` は同じ形で、`room_booking_claims` の DELETE が増える。`ApplyExpired` / `ApplyNoShowRecorded` の `actor_code` は予約者ではなく仕組みを表す定数で、その値は資料の未決（[marshaller.md](marshaller.md) §3）

### `FindByID`（current 行が一次データ）

```go
func (r *ReservationRepository) FindByID(ctx context.Context, id reservation.ID) (reservation.Reservation, error) {
	q, err := queries(ctx)
	if err != nil {
		return nil, err
	}
	res, err := q.GetReservation(ctx, id.Value())
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("予約 %s の取得: %w", id.Value(), ErrNotFound)
		}
		return nil, fmt.Errorf("予約 %s の取得: %w", id.Value(), err)
	}
	var deadline *sqlcgen.TentativeHoldDeadline
	if res.Status == statusTentative {
		d, err := q.GetTentativeHoldDeadline(ctx, id.Value())
		if err != nil {
			return nil, fmt.Errorf("予約 %s の仮押さえ期限の取得: %w", id.Value(), err)
		}
		deadline = &d
	}
	var noShowAt []time.Time
	if res.Status == statusConfirmed {
		noShowAt, err = q.ListReservationNoShowRecordedAt(ctx, id.Value())
		if err != nil {
			return nil, fmt.Errorf("予約 %s の無断不利用の記録の取得: %w", id.Value(), err)
		}
	}
	agg, err := reservationRowToReservation(res, deadline, noShowAt)
	if err != nil {
		return nil, fmt.Errorf("予約 %s の復元: %w", id.Value(), err)
	}
	return agg, nil
}
```

- 復元は `reservations` と、状態に応じた従属行だけから行う。仮押さえ中は `tentative_hold_deadlines`（必須）、確定済みは無断不利用の記録（任意。仮定の 9 表目を基底イベントと JOIN した `occurred_at`）。`reservation_base_events` を読んで畳み込まない。current 行が現在の姿の一次データで、`current_version` がそこにあるからである
- 仮押さえなのに期限の行が無いのはデータ破損なので、`ErrNotFound` にせずそのまま error を返す。状態が仮押さえでなければ期限の行を読まない
- 無断不利用の記録は無いことが正常なので `:many` で読み、0 行を「起きていない」として渡す。`:one` の `ErrNoRows` を「無い」に読み替える分岐を作らない
- `reservationRowToReservation` は [marshaller.md](marshaller.md) §3
