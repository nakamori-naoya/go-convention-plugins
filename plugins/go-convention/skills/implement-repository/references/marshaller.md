# marshaller

**marshaller は、ドメインの値と sqlc の行・Params を往復させる、同じ package の純粋関数である。** ctx を受けず、DB を触らず、業務判断をしない。リポジトリのメソッドは「query を呼ぶ順番」だけを持ち、値の写し替えは全部ここに寄せる。

## 1. 置き場と形

| 項目 | 規則 |
|---|---|
| package | リポジトリと同じ `rdb`。別 package にしない（別にすると sqlcgen の型とドメインの型を両方 export する理由が生まれる） |
| ファイル | `rdb/{aggregate}_marshaller.go`。`status` / `event_type` / `actor_code` の文字列定数もここ |
| 可視性 | 非公開関数。テストは公開メソッド（`FindByID` / `Apply*`）を通して観測する |
| 引数 | ドメインの値（イベント・状態型）か sqlc の行。`context.Context` を取らない |
| 返り値 | ドメイン → 行は error なし。行 → ドメインは `(T, error)`（`New*` が拒んだ分だけ） |

## 2. 命名 `{元}To{先}`

読み手が方向を関数名だけで判断できる名前にする。

| 方向 | 形 | 例 |
|---|---|---|
| ドメインイベント → Params | `{event}To{Query}Params` | `heldToInsertReservationParams(evt reservation.Held) sqlcgen.InsertReservationParams` |
| 共通イベント interface → Params | `eventTo{Query}Params` | `eventToInsertReservationBaseEventParams(evt reservation.Event, eventType, actor string) sqlcgen.InsertReservationBaseEventParams` |
| 状態型 → Params（通常型） | `{state}To{Query}Params` | `waitingToInsertWaitlistParams(w waitlist.Waiting) sqlcgen.InsertWaitlistParams` |
| 行 → 集約 | `{table}RowTo{Aggregate}` | `reservationRowToReservation(res sqlcgen.Reservation, deadline *sqlcgen.TentativeHoldDeadline, noShowAt []time.Time) (reservation.Reservation, error)` |
| NULL 列 → Go の値 | `{pgtype}To{Go}` | `timestamptzToTime(t pgtype.Timestamptz) (time.Time, bool)` |

使わない名前: `ToParams` / `ToInsertParams`（元が無い）、`From{X}` / `Convert{X}` / `Map{X}`（方向が読めない）、`Build{X}` / `Make{X}`（生成に見える）。元の型が interface なら `event` のように interface 名を、状態型なら状態名を小文字で書く。

## 3. 行 → ドメインは `New*` と `Restore*` だけを通す

行の primitive を VO の `New*` に通し、集約は状態ごとの `Restore*` で組み立てる。struct リテラルは書けない（別 package の非公開フィールドで、型が塞いでいる）。`New*` が拒んだら、それは行が VO の不変条件を満たしていない＝データ破損であり、リポジトリはそのまま error を返す（`ErrNotFound` にも業務の sentinel にもしない）。

```go
package rdb

import (
	"fmt"
	"time"

	"example.com/roomflow/rdb/sqlcgen"
	"example.com/roomflow/reservation"
)

const (
	statusTentative = "tentative"
	statusConfirmed = "confirmed"
	statusCancelled = "cancelled"
	statusExpired   = "expired"

	eventTypeTentativeCreated = "tentative_created"
	eventTypeConfirmed        = "confirmed"
	eventTypeCancelled        = "cancelled"
	eventTypeExpired          = "expired"
	eventTypeNoShowRecorded   = "no_show_recorded"

	// 仕組みが起こすイベントの actor_code。予約者ではない。
	// データモデル資料では「期限管理」の actor の値は未決で、物理設計で決まるまでの仮の定数。報告に載せる。
	actorDeadlineKeeper = "期限管理"  // ApplyExpired
	actorNoShowKeeper   = "不利用判定" // ApplyNoShowRecorded（無断不利用は資料の範囲外。同じく仮の定数）
)

// reservationRowToReservation は current 行と、状態に応じた従属行から集約を復元する。
// deadline は仮押さえ中だけ非 nil、noShowAt は確定済みだけ 0 件か 1 件（他の状態では nil を渡す）。
func reservationRowToReservation(res sqlcgen.Reservation, deadline *sqlcgen.TentativeHoldDeadline, noShowAt []time.Time) (reservation.Reservation, error) {
	id, err := reservation.NewID(res.ReservationID)
	if err != nil {
		return nil, err
	}
	customer, err := reservation.NewCustomerID(res.CustomerCode)
	if err != nil {
		return nil, err
	}
	room, err := reservation.NewRoomCode(res.RoomCode)
	if err != nil {
		return nil, err
	}
	slot, err := reservation.NewTimeSlot(room, res.StartsAt.UTC(), res.EndsAt.UTC())
	if err != nil {
		return nil, err
	}
	v, err := reservation.NewVersion(int(res.CurrentVersion))
	if err != nil {
		return nil, err
	}
	switch res.Status {
	case statusTentative:
		if deadline == nil {
			return nil, fmt.Errorf("状態 %s なのに仮押さえ期限の行がない", res.Status)
		}
		return reservation.RestoreTentative(id, customer, slot, reservation.RestoreHoldDeadline(deadline.ExpiresAt.UTC()), v), nil
	case statusConfirmed:
		switch len(noShowAt) {
		case 0:
			return reservation.RestoreConfirmed(id, customer, slot, time.Time{}, v), nil // ゼロ値は「起きていない」
		case 1:
			return reservation.RestoreConfirmed(id, customer, slot, noShowAt[0].UTC(), v), nil
		}
		return nil, fmt.Errorf("無断不利用の記録が %d 件ある", len(noShowAt))
	case statusCancelled:
		return reservation.RestoreCancelled(id, customer, slot, v), nil
	case statusExpired:
		return reservation.RestoreExpired(id, customer, slot, v), nil
	}
	return nil, fmt.Errorf("状態 %q は未知", res.Status)
}
```

| 規則 | 理由 |
|---|---|
| `status` の値で `Restore*` を選ぶ。未知の値は error | 状態型は sealed で、文字列から型を選ぶのはここ 1 か所。既定の状態へ丸めない |
| 時刻は `Restore*` / `New*` に渡す直前に `.UTC()` を通す | pgx が返す `time.Time` は Local を持つ。`New*` が正規化するかに関わらず一律に UTC にし、`==` で比べられる値にする |
| 文脈はここで足さない。呼び手（`FindByID`）が `fmt.Errorf("予約 %s の復元: %w", ...)` で 1 回足す | 各 `New*` の error に個別の文脈を足すと、同じ ID が何段にも重なる |
| イベント型の復元は current 行（`reservations` と従属行）が正式な定義 | `reservation_base_events` を読んで畳み込まない。current 行に `current_version` があり、イベントの再生は要らない |
| 「起きたかどうか」を表す値は、資料の流儀（全列 NOT NULL）に従い current 行の NULL 列にせず、イベント表の有無で持つ。無ければゼロ値を `Restore*` に渡す | 無断不利用の時刻は `reservation_no_show_recorded_events`（資料に無い仮定の 9 表目）を基底イベントと JOIN した `occurred_at` が一次データ。2 件以上はデータ破損（集約が 1 回しか記録しない）なので error にし、先頭で丸めない |
| 非ルートエンティティは、`:many` で集めた子行を VO の `New*` に通し、ルートの `Restore*` にスライスで渡す | 子の生成もルート経由。子の struct リテラルも書けない |

## 4. ドメイン → 行は getter だけを読む

イベント（または状態型）の getter から Params を組み立てる。値はすべてドメインから来るので失敗しない。時刻も版もリポジトリが作らない。

```go
func heldToInsertReservationParams(evt reservation.Held) sqlcgen.InsertReservationParams {
	slot := evt.Slot()
	return sqlcgen.InsertReservationParams{
		ReservationID:  evt.ReservationID().Value(),
		RoomCode:       slot.Room().Value(),
		CustomerCode:   evt.Customer().Value(),
		StartsAt:       slot.Start(),
		EndsAt:         slot.End(),
		Status:         statusTentative,
		CurrentVersion: int32(evt.Version().Value()),
		CreatedAt:      evt.OccurredAt(),
		UpdatedAt:      evt.OccurredAt(),
	}
}

func heldToInsertRoomBookingClaimParams(evt reservation.Held) sqlcgen.InsertRoomBookingClaimParams {
	slot := evt.Slot()
	return sqlcgen.InsertRoomBookingClaimParams{
		ReservationID: evt.ReservationID().Value(),
		RoomCode:      slot.Room().Value(),
		StartsAt:      slot.Start(),
		EndsAt:        slot.End(),
		CreatedAt:     evt.OccurredAt(),
	}
}

func heldToInsertTentativeHoldDeadlineParams(evt reservation.Held) sqlcgen.InsertTentativeHoldDeadlineParams {
	return sqlcgen.InsertTentativeHoldDeadlineParams{
		ReservationID: evt.ReservationID().Value(),
		ExpiresAt:     evt.Deadline().At(),
		CreatedAt:     evt.OccurredAt(),
	}
}

// 基底イベントの行は全イベントで同じ形なので、共通 interface を元にする。
func eventToInsertReservationBaseEventParams(evt reservation.Event, eventType string, actor string) sqlcgen.InsertReservationBaseEventParams {
	return sqlcgen.InsertReservationBaseEventParams{
		ReservationID: evt.ReservationID().Value(),
		EventType:     eventType,
		Version:       int32(evt.Version().Value()),
		ActorCode:     actor,
		OccurredAt:    evt.OccurredAt(),
	}
}

func heldToInsertReservationTentativeCreatedEventParams(evt reservation.Held, baseEventID int64) sqlcgen.InsertReservationTentativeCreatedEventParams {
	slot := evt.Slot()
	return sqlcgen.InsertReservationTentativeCreatedEventParams{
		BaseEventID:  baseEventID,
		RoomCode:     slot.Room().Value(),
		CustomerCode: evt.Customer().Value(),
		StartsAt:     slot.Start(),
		EndsAt:       slot.End(),
		ExpiresAt:    evt.Deadline().At(),
	}
}

// 楽観ロック付き UPDATE。照合キーは 1 つ前の版。
func eventToUpdateReservationCurrentParams(evt reservation.Event, status string) sqlcgen.UpdateReservationCurrentParams {
	return sqlcgen.UpdateReservationCurrentParams{
		ReservationID:   evt.ReservationID().Value(),
		Status:          status,
		CurrentVersion:  int32(evt.Version().Value()),
		UpdatedAt:       evt.OccurredAt(),
		ExpectedVersion: int32(evt.Version().Value() - 1),
	}
}
```

| 規則 | 理由 |
|---|---|
| `created_at` / `updated_at` / `occurred_at` はすべて `evt.OccurredAt()`。`time.Now()` を呼ばない | 資料の「値を決める事実」がイベントの発生日時である。リポジトリが時刻を作ると、資料の After と突き合わせられない |
| `status` / `event_type` の文字列はこのファイルの定数だけから出す | DDL の CHECK と資料の値域に対応する語が 1 か所に閉じる |
| `int32(...)` の変換は marshaller で行い、リポジトリのメソッドに書かない | sqlc の型都合を写し替えの場所に閉じる |
| 詳細イベントの `base_event_id` は引数で受ける | 基底イベントの `RETURNING id` を受け取れるのはリポジトリだけで、marshaller は DB を触らない |
| 通常型の状態ごとの Params（`waitingTo*` / `endedTo*`）も同じ形。和型の型スイッチはリポジトリ側 | marshaller の引数は具体型。型スイッチを marshaller に持ち込むと `default` の扱いが 2 か所に散る |

## 5. NULL 列

sqlc（`sql_package: pgx/v5`）は NULL 許可列を `pgtype.Timestamptz` / `pgtype.Text` 等で生成する。marshaller はそれを `(T, bool)` に写し、`pgtype` の型をドメインに渡さない。逆方向は `pgtype.Timestamptz{Time: at, Valid: true}` を組み立て、無いときは `Valid: false`（ゼロ値）のままにする。

題材のデータモデル資料は全列 NOT NULL なので、例は資料に無い仮定の集約「予約待ち」（通常型。[standard-and-event-sourced.md](standard-and-event-sourced.md) §3）の `waitlists.ended_at timestamptz NULL`（終了した予約待ちだけが持つ終了時刻）で示す。

```go
package rdb

import (
	"time"

	"github.com/jackc/pgx/v5/pgtype"

	"example.com/roomflow/rdb/sqlcgen"
	"example.com/roomflow/waitlist"
)

// 通常型の Update: 終了した予約待ちは ended_at を持ち、予約待ち中は持たない（Valid: false のまま）。
func endedToUpdateWaitlistParams(w waitlist.Ended) sqlcgen.UpdateWaitlistParams {
	return sqlcgen.UpdateWaitlistParams{
		WaitlistID: w.ID().Value(),
		Status:     waitlistStatusEnded,
		EndedAt:    pgtype.Timestamptz{Time: w.EndedAt(), Valid: true},
	}
}

func waitingToUpdateWaitlistParams(w waitlist.Waiting) sqlcgen.UpdateWaitlistParams {
	return sqlcgen.UpdateWaitlistParams{
		WaitlistID: w.ID().Value(),
		Status:     waitlistStatusWaiting,
	}
}

// 行 → ドメイン。NULL 列は (T, bool) に写してから Restore* に渡す。
func timestamptzToTime(t pgtype.Timestamptz) (time.Time, bool) {
	if !t.Valid {
		return time.Time{}, false
	}
	return t.Time.UTC(), true
}
```

`waitlistRowToWaitlist` は `status` が終了のとき `timestamptzToTime(row.EndedAt)` の `ok` が偽ならデータ破損として error を返し、ゼロ時刻で `RestoreEnded` を呼ばない。`*time.Time` や `sql.Null*` を使わない。NOT NULL 列は sqlc の override で `time.Time` にする（[sqlc-and-tx.md](sqlc-and-tx.md) §1）ので、`pgtype` が現れるのは NULL 列だけである。
