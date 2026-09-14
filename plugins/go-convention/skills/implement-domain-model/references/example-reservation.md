# 題材の実装例 — 予約集約（package `reservation`）

資料「ドメインモデル — 貸会議室の予約」の集約「予約」と、その値オブジェクト・ドメインイベント・永続化ポートを Go で写した完全な例である。**書き始める前に一度読み、この形を写す。** 各規則の理由は [value-object.md](value-object.md) / [aggregate-typestate.md](aggregate-typestate.md) / [events.md](events.md) にあり、資料からの導き方は [from-domain-model-doc.md](from-domain-model-doc.md) にある。

module は `example.com/roomflow`。ディレクトリ構成は上位の開発規約が決めるので、例は import path を短くするため平らに置いている。1 ファイルにまとめているのも例のためで、実装では型ごとにファイルを分ける（`id.go` / `time_slot.go` / `reservation.go` / `event.go` / `errors.go` / `repository.go`）。

## 資料の要素・操作と Go の対応

| 資料 | 種別 | Go |
|---|---|---|
| 予約番号 / 予約者 / 会議室 | 識別子の値オブジェクト | `ID` / `CustomerID` / `RoomCode`（`NewX(s string) (X, error)`。空を拒む） |
| 利用枠 | 値オブジェクト | `TimeSlot`（`NewTimeSlot`。利用開始が利用終了より前でなければ拒む）。操作「重なるか」→ `Overlaps` |
| 仮押さえ期限 | 値オブジェクト | `HoldDeadline`（`NewHoldDeadline(heldAt)` は 15 分後を導く。error なし）。操作「到来したか」→ `HasArrived` |
| 顧客の予約資格 | 値オブジェクト | `Eligibility`（`NewEligibility` が生成の条件そのもの。error なし）。操作「新しい申込みができるか」→ `CanApply` |
| 版（資料に無い。イベント型の永続化に要る） | 値オブジェクト | `Version`（`NewVersion` は 1 未満を拒む。`Next` / `Value`） |
| 予約 | 集約ルート | 和型 `Reservation`（封じた interface）と状態型 `Tentative` / `Confirmed` / `Cancelled` / `Expired` |
| 現在有効な予約 | 資料の語（利用枠を占有する予約） | 部分和型 `Active`（`Tentative` と `Confirmed` が満たす） |
| 操作「仮押さえ予約を成立させる」 | 生成 | `Hold(id, customer, slot, eligibility, at) (HoldResult, error)` |
| 操作「確定する」 | 遷移 | `(Tentative) Confirm(at, by) (ConfirmResult, error)` |
| 操作「取り消す」 | 遷移 | `(Tentative) Cancel` / `(Confirmed) Cancel` `(at, by) (CancelResult, error)` |
| 操作「期限到来を反映する」 | 遷移（拒まない） | `(Tentative) Expire(at) (ExpireResult, bool)` |
| 操作「無断不利用を記録する」 | 状態を変えない操作（拒まない） | `(Confirmed) RecordNoShow(at) (NoShowResult, bool)` |
| 状態と型の分割「確定予約は確定を呼べない型にする」 | 絞り込み | `AsTentative(r) (Tentative, error)` / `AsActive(r) (Active, error)`。違う状態なら sentinel |
| （資料に無い。永続化からの復元） | 復元 | `RestoreTentative` / `RestoreConfirmed` / `RestoreCancelled` / `RestoreExpired` |
| 仮押さえ予約が成立した / 予約が確定した / 予約が取り消された / 仮押さえ期限が到来した / 無断不利用が記録された | ドメインイベント | `Held` / `ConfirmedEvent` / `CancelledEvent` / `ExpiredEvent` / `NoShowRecorded`（和型 `Event`） |
| 拒むときの理由（7 行）＋終端状態から戻らない（不変条件） | sentinel | `ErrOverlappingSlot` … `ErrAlreadyExpired`（9 つ）。VO の生成の条件を拒む 5 つと和型の nil を拒む 1 つは、資料に無い Go の都合として別の var ブロック |
| （資料に無い。永続化ポート） | interface | `Repository`（イベント型。`FindByID` ＋ `Apply{Event}`） |

資料にあって Go に無いもの: 「重なる利用枠の仮押さえ」の判定は集約の内側では確かめられない（資料「集約の境界」）ので、`Hold` は `ErrOverlappingSlot` を返さない。生成を呼ぶ側の重なり検査と DB 制約の翻訳が返す。

## コード

```go
package reservation

import (
	"context"
	"errors"
	"slices"
	"time"
)

// 資料「予約」集約。import path を短くするため例は平らに置く（ディレクトリ構成は上位の開発規約が決める）。

// ---- 値オブジェクト ----

// ID は予約番号。
type ID struct{ v string }

// NewID は空でない予約番号を作る。
func NewID(s string) (ID, error) {
	if s == "" {
		return ID{}, ErrIDRequired
	}
	return ID{v: s}, nil
}

func (id ID) Value() string { return id.v }

// CustomerID は予約者（顧客）の識別子。この文脈に顧客のエンティティは無い。
type CustomerID struct{ v string }

func NewCustomerID(s string) (CustomerID, error) {
	if s == "" {
		return CustomerID{}, ErrCustomerIDRequired
	}
	return CustomerID{v: s}, nil
}

func (c CustomerID) Value() string { return c.v }

// RoomCode は会議室の識別子。会議室の管理はこの文脈の外にある。
type RoomCode struct{ v string }

func NewRoomCode(s string) (RoomCode, error) {
	if s == "" {
		return RoomCode{}, ErrRoomCodeRequired
	}
	return RoomCode{v: s}, nil
}

func (r RoomCode) Value() string { return r.v }

// TimeSlot は利用枠。「会議室、利用開始、利用終了」の組で、時間帯は半開区間 [start, end)。
type TimeSlot struct {
	room  RoomCode
	start time.Time // UTC
	end   time.Time // UTC
}

// NewTimeSlot は生成の条件「会議室と、利用開始より後の利用終了が揃うこと」を確かめる。
// 時刻は UTC に正規化し、== で比べられる値にする。
func NewTimeSlot(room RoomCode, start, end time.Time) (TimeSlot, error) {
	start, end = start.UTC(), end.UTC()
	if !start.Before(end) {
		return TimeSlot{}, ErrTimeSlotNotOrdered
	}
	return TimeSlot{room: room, start: start, end: end}, nil
}

func (s TimeSlot) Room() RoomCode   { return s.room }
func (s TimeSlot) Start() time.Time { return s.start }
func (s TimeSlot) End() time.Time   { return s.end }

// Overlaps は操作「重なるか」。同じ会議室で時間帯が一部でも重なるとき真。隣接（end == 次の start）は偽。
func (s TimeSlot) Overlaps(o TimeSlot) bool {
	return s.room == o.room && s.start.Before(o.end) && o.start.Before(s.end)
}

// holdDuration は仮押さえ期限までの長さ（資料: 成立時刻の 15 分後）。
const holdDuration = 15 * time.Minute

// HoldDeadline は仮押さえ期限。仮押さえ予約だけが持つ。
type HoldDeadline struct{ at time.Time }

// NewHoldDeadline は仮押さえ成立時刻から期限を導く。拒む組が無いので error を返さない。
func NewHoldDeadline(heldAt time.Time) HoldDeadline {
	return HoldDeadline{at: heldAt.UTC().Add(holdDuration)}
}

// RestoreHoldDeadline は保存済みの期限の時刻から復元する。New は成立時刻から導くため、復元には別の入口が要る。
func RestoreHoldDeadline(at time.Time) HoldDeadline {
	return HoldDeadline{at: at.UTC()}
}

func (d HoldDeadline) At() time.Time { return d.at }

// HasArrived は操作「到来したか」。判定時刻が期限と同じか後なら真（同時刻は到来）。
func (d HoldDeadline) HasArrived(at time.Time) bool {
	return !at.Before(d.at)
}

// 顧客の予約資格の導出に使う数（資料: 直近 30 日で 3 回、3 回目から 14 日間）。
const (
	noShowWindow    = 30 * 24 * time.Hour
	noShowThreshold = 3
	suspension      = 14 * 24 * time.Hour
)

// Eligibility は顧客の予約資格。その顧客の予約で起きた無断不利用と判定時刻から導出する値で、集約は持たない。
type Eligibility struct {
	customer       CustomerID
	suspendedUntil time.Time // 仮押さえ停止の終了時刻。ゼロ値は「予約可能」
}

// NewEligibility は生成の条件そのもの。判定時刻から 30 日前までに無断不利用が 3 回起きていて、
// 3 回目から 14 日が経っていなければ仮押さえ停止中（停止開始は 3 回目の時刻）、それ以外は予約可能。
// 拒む組が無いので error を返さない。
func NewEligibility(customer CustomerID, noShowAt []time.Time, at time.Time) Eligibility {
	at = at.UTC()
	var recent []time.Time
	for _, t := range noShowAt {
		t = t.UTC()
		if !t.After(at) && !t.Before(at.Add(-noShowWindow)) {
			recent = append(recent, t)
		}
	}
	if len(recent) < noShowThreshold {
		return Eligibility{customer: customer}
	}
	slices.SortFunc(recent, time.Time.Compare)
	until := recent[noShowThreshold-1].Add(suspension)
	if !at.Before(until) {
		return Eligibility{customer: customer}
	}
	return Eligibility{customer: customer, suspendedUntil: until}
}

func (e Eligibility) Customer() CustomerID { return e.customer }

// CanApply は操作「新しい申込みができるか」。予約可能なら真、仮押さえ停止中なら偽。停止終了時刻と同時刻は予約可能。
func (e Eligibility) CanApply(at time.Time) bool {
	return !at.Before(e.suspendedUntil)
}

// Version は集約の版。イベント型の永続化で楽観ロックと base_events.version に使う。1 以上。
type Version struct{ v int }

func NewVersion(n int) (Version, error) {
	if n < 1 {
		return Version{}, ErrVersionNotPositive
	}
	return Version{v: n}, nil
}

func (v Version) Next() Version { return Version{v: v.v + 1} }
func (v Version) Value() int    { return v.v }

// ---- 集約「予約」: 和型と状態型 ----

// Reservation は予約の和型。封じた interface で、状態型は Tentative / Confirmed / Cancelled / Expired の 4 つ。
// //sumtype:decl は型スイッチの網羅を lint（gochecksumtype）に検査させる印。
//
//sumtype:decl
type Reservation interface {
	ID() ID
	Customer() CustomerID
	Slot() TimeSlot
	Version() Version
	isReservation()
}

// Active は資料の「現在有効な予約」（利用枠を占有する予約）。Tentative と Confirmed が満たす。
type Active interface {
	Reservation
	Cancel(at time.Time, by CustomerID) (CancelResult, error)
}

// core は全状態が持つ値（資料「持つもの」のうち状態によらないもの）。
type core struct {
	id       ID
	customer CustomerID
	slot     TimeSlot
	version  Version
}

func (c core) ID() ID               { return c.id }
func (c core) Customer() CustomerID { return c.customer }
func (c core) Slot() TimeSlot       { return c.slot }
func (c core) Version() Version     { return c.version }
func (core) isReservation()         {}

func (c core) withVersion(v Version) core {
	c.version = v
	return c
}

// Tentative は仮押さえ予約。仮押さえ期限を持つ唯一の状態。
type Tentative struct {
	core
	deadline HoldDeadline
}

func (t Tentative) Deadline() HoldDeadline { return t.deadline }

// Confirmed は確定予約。仮押さえ期限を持たず、確定を呼べない。
type Confirmed struct {
	core
	noShowAt time.Time // 無断不利用が起きた時刻。ゼロ値は「起きていない」
}

// NoShowAt は無断不利用が起きた時刻と、起きたかどうか。
func (c Confirmed) NoShowAt() (time.Time, bool) {
	return c.noShowAt, !c.noShowAt.IsZero()
}

// Cancelled は取消済み予約。終端で、操作を一つも公開しない。
type Cancelled struct{ core }

// Expired は期限切れ予約。終端で、人の取消（Cancelled）と区別して残す。
type Expired struct{ core }

// ---- 遷移結果型 ----

// Transition は操作の結果。Next が新しい状態の値、Event が発したイベント。package 内で 1 つ。
type Transition[S Reservation, E Event] struct {
	Next  S
	Event E
}

type (
	HoldResult    = Transition[Tentative, Held]
	ConfirmResult = Transition[Confirmed, ConfirmedEvent]
	CancelResult  = Transition[Cancelled, CancelledEvent]
	ExpireResult  = Transition[Expired, ExpiredEvent]
	NoShowResult  = Transition[Confirmed, NoShowRecorded]
)

// ---- 生成と操作（資料の操作と 1:1。時刻と ID は引数で受ける） ----

// Hold は操作「仮押さえ予約を成立させる」。
// 事前条件: 資格の顧客が予約者と同じで、予約可能であること。
// 「同じ会議室の重なる利用枠に有効な予約が無いこと」は集約の内側では確かめられないので、呼ぶ側と DB 制約が守る。
func Hold(id ID, customer CustomerID, slot TimeSlot, eligibility Eligibility, at time.Time) (HoldResult, error) {
	if eligibility.Customer() != customer {
		return HoldResult{}, ErrEligibilityMismatch
	}
	if !eligibility.CanApply(at) {
		return HoldResult{}, ErrCustomerSuspended
	}
	at = at.UTC()
	v := Version{v: 1}
	deadline := NewHoldDeadline(at)
	next := Tentative{core: core{id: id, customer: customer, slot: slot, version: v}, deadline: deadline}
	evt := Held{
		base:     base{reservationID: id, version: v, occurredAt: at},
		customer: customer,
		slot:     slot,
		deadline: deadline,
	}
	return HoldResult{Next: next, Event: evt}, nil
}

// Confirm は操作「確定する」。事前条件は資料の順に確かめる: 期限が到来していない → 呼び手が予約者本人。
func (t Tentative) Confirm(at time.Time, by CustomerID) (ConfirmResult, error) {
	if t.deadline.HasArrived(at) {
		return ConfirmResult{}, ErrHoldDeadlinePassed
	}
	if by != t.customer {
		return ConfirmResult{}, ErrNotOwner
	}
	at = at.UTC()
	v := t.version.Next()
	return ConfirmResult{
		Next:  Confirmed{core: t.core.withVersion(v)},
		Event: ConfirmedEvent{base: base{reservationID: t.id, version: v, occurredAt: at}, by: by},
	}, nil
}

// Cancel は操作「取り消す」（仮押さえ予約）。
func (t Tentative) Cancel(at time.Time, by CustomerID) (CancelResult, error) {
	return t.core.cancel(at, by)
}

// Cancel は操作「取り消す」（確定予約）。
func (c Confirmed) Cancel(at time.Time, by CustomerID) (CancelResult, error) {
	return c.core.cancel(at, by)
}

// cancel は両状態に共通の「取り消す」。事前条件は資料の順: 取消時刻が利用開始より前 → 呼び手が予約者本人。
func (c core) cancel(at time.Time, by CustomerID) (CancelResult, error) {
	if !at.Before(c.slot.Start()) {
		return CancelResult{}, ErrSlotAlreadyStarted
	}
	if by != c.customer {
		return CancelResult{}, ErrNotOwner
	}
	at = at.UTC()
	v := c.version.Next()
	return CancelResult{
		Next:  Cancelled{core: c.withVersion(v)},
		Event: CancelledEvent{base: base{reservationID: c.id, version: v, occurredAt: at}, by: by, slot: c.slot},
	}, nil
}

// Expire は操作「期限到来を反映する」。拒まない。期限が到来していなければ何も変えず false。
func (t Tentative) Expire(at time.Time) (ExpireResult, bool) {
	if !t.deadline.HasArrived(at) {
		return ExpireResult{}, false
	}
	at = at.UTC()
	v := t.version.Next()
	return ExpireResult{
		Next:  Expired{core: t.core.withVersion(v)},
		Event: ExpiredEvent{base: base{reservationID: t.id, version: v, occurredAt: at}, slot: t.slot},
	}, true
}

// noShowGrace は利用開始から無断不利用と見なすまでの長さ（資料: 15 分）。
const noShowGrace = 15 * time.Minute

// RecordNoShow は操作「無断不利用を記録する」。拒まない。
// 判定時刻が利用開始から 15 分を過ぎていなければ、または既に記録済みなら、何も変えず false。
// 「事前の取消が無い」は Confirmed 型であることが保証する。
func (c Confirmed) RecordNoShow(at time.Time) (NoShowResult, bool) {
	if !c.noShowAt.IsZero() {
		return NoShowResult{}, false
	}
	if !at.After(c.slot.Start().Add(noShowGrace)) {
		return NoShowResult{}, false
	}
	at = at.UTC()
	v := c.version.Next()
	return NoShowResult{
		Next:  Confirmed{core: c.core.withVersion(v), noShowAt: at},
		Event: NoShowRecorded{base: base{reservationID: c.id, version: v, occurredAt: at}},
	}, true
}

// ---- 絞り込みと復元 ----

// AsTentative は和型を仮押さえ予約へ絞り込む。違う状態なら、その状態を表す sentinel を返す。
// 状態は全部列挙する。和型は封じてあるので default に来るのは nil だけで、それも丸めずに返す。
func AsTentative(r Reservation) (Tentative, error) {
	switch r := r.(type) {
	case Tentative:
		return r, nil
	case Confirmed:
		return Tentative{}, ErrAlreadyConfirmed
	case Cancelled:
		return Tentative{}, ErrAlreadyCancelled
	case Expired:
		return Tentative{}, ErrAlreadyExpired
	default:
		return Tentative{}, ErrNoReservation
	}
}

// AsActive は和型を「現在有効な予約」へ絞り込む。
func AsActive(r Reservation) (Active, error) {
	switch r := r.(type) {
	case Tentative:
		return r, nil
	case Confirmed:
		return r, nil
	case Cancelled:
		return nil, ErrAlreadyCancelled
	case Expired:
		return nil, ErrAlreadyExpired
	default:
		return nil, ErrNoReservation
	}
}

// Restore* は保存済みの値から状態型を復元する。生成の条件は保存時に満たしているので確かめない。
func RestoreTentative(id ID, customer CustomerID, slot TimeSlot, deadline HoldDeadline, v Version) Tentative {
	return Tentative{core: core{id: id, customer: customer, slot: slot, version: v}, deadline: deadline}
}

func RestoreConfirmed(id ID, customer CustomerID, slot TimeSlot, noShowAt time.Time, v Version) Confirmed {
	return Confirmed{core: core{id: id, customer: customer, slot: slot, version: v}, noShowAt: noShowAt.UTC()}
}

func RestoreCancelled(id ID, customer CustomerID, slot TimeSlot, v Version) Cancelled {
	return Cancelled{core: core{id: id, customer: customer, slot: slot, version: v}}
}

func RestoreExpired(id ID, customer CustomerID, slot TimeSlot, v Version) Expired {
	return Expired{core: core{id: id, customer: customer, slot: slot, version: v}}
}

// ---- ドメインイベント（封じた和型。版を持つ） ----

// Event は予約のドメインイベントの和型。
//
//sumtype:decl
type Event interface {
	ReservationID() ID
	Version() Version
	OccurredAt() time.Time
	isEvent()
}

// base は全イベントが持つ値。version は Next.Version() と一致する。
type base struct {
	reservationID ID
	version       Version
	occurredAt    time.Time // UTC
}

func (b base) ReservationID() ID     { return b.reservationID }
func (b base) Version() Version      { return b.version }
func (b base) OccurredAt() time.Time { return b.occurredAt }
func (base) isEvent()                {}

// Held は「仮押さえ予約が成立した」。生成のイベントなので、予約の値を全部持つ。
type Held struct {
	base
	customer CustomerID
	slot     TimeSlot
	deadline HoldDeadline
}

func (e Held) Customer() CustomerID   { return e.customer }
func (e Held) Slot() TimeSlot         { return e.slot }
func (e Held) Deadline() HoldDeadline { return e.deadline }

// ConfirmedEvent は「予約が確定した」。状態型 Confirmed と名前が衝突するので Event 接尾辞を付ける。
type ConfirmedEvent struct {
	base
	by CustomerID
}

func (e ConfirmedEvent) By() CustomerID { return e.by }

// CancelledEvent は「予約が取り消された」。繰上げ判断が受けるので利用枠を持つ。
type CancelledEvent struct {
	base
	by   CustomerID
	slot TimeSlot
}

func (e CancelledEvent) By() CustomerID { return e.by }
func (e CancelledEvent) Slot() TimeSlot { return e.slot }

// ExpiredEvent は「仮押さえ期限が到来した」。繰上げ判断が受けるので利用枠を持つ。
type ExpiredEvent struct {
	base
	slot TimeSlot
}

func (e ExpiredEvent) Slot() TimeSlot { return e.slot }

// NoShowRecorded は「無断不利用が記録された」。記録した時刻は OccurredAt。
type NoShowRecorded struct{ base }

// ---- sentinel（資料「拒むときの理由」と 1:1。文言は日本語・句点なし・何が拒まれたか） ----

var (
	ErrOverlappingSlot     = errors.New("重なる利用枠には仮押さえできない")       // 重なる利用枠の仮押さえ。生成を呼ぶ側と DB 制約の翻訳が返す
	ErrCustomerSuspended   = errors.New("仮押さえ停止中の顧客は新しい申込みができない") // 仮押さえ停止中顧客による新しい申込み
	ErrEligibilityMismatch = errors.New("予約資格の顧客が予約者と一致しない")      // 生成の条件「資格の顧客が予約者と同じ」
	ErrHoldDeadlinePassed  = errors.New("仮押さえ期限以降は確定できない")        // 仮押さえ期限以降の確定
	ErrAlreadyConfirmed    = errors.New("確定済みの予約は再確定できない")        // 確定済み予約の再確定
	ErrNotOwner            = errors.New("他人の予約は操作できない")           // 他人の予約または予約待ちの取消（確定にも使う）
	ErrSlotAlreadyStarted  = errors.New("利用開始以降の予約は取り消せない")       // 利用開始以降の予約取消
	ErrAlreadyCancelled    = errors.New("取消済みの予約は操作できない")         // 終端状態から戻らない（取消済み）
	ErrAlreadyExpired      = errors.New("期限切れの予約は操作できない")         // 終端状態から戻らない（期限切れ）
)

// 資料の「拒むときの理由」には無いが Go の型の都合で要る sentinel。
// 値オブジェクトの生成の条件（「揃わない組は存在しない」）と、和型に nil が渡されたとき。
var (
	ErrIDRequired         = errors.New("予約番号が空の予約は作れない")
	ErrCustomerIDRequired = errors.New("予約者が空の予約は作れない")
	ErrRoomCodeRequired   = errors.New("会議室が空の利用枠は作れない")
	ErrTimeSlotNotOrdered = errors.New("利用終了が利用開始より後でない利用枠は作れない")
	ErrVersionNotPositive = errors.New("1 未満の版は作れない")
	ErrNoReservation      = errors.New("予約が無い値は絞り込めない") // 和型が nil
)

// ---- 永続化ポート（イベント型。集約と同じ package に集約ごと 1 つ） ----

// Repository は予約の永続化ポート。FindByID は和型を返し、状態指定の取得は置かない。
// イベント型なので、保存は集約ではなくイベントを受け取る Apply{Event} で行う。tx は ctx から受け取る。
type Repository interface {
	FindByID(ctx context.Context, id ID) (Reservation, error)
	ApplyHeld(ctx context.Context, evt Held) error
	ApplyConfirmed(ctx context.Context, evt ConfirmedEvent) error
	ApplyCancelled(ctx context.Context, evt CancelledEvent) error
	ApplyExpired(ctx context.Context, evt ExpiredEvent) error
	ApplyNoShowRecorded(ctx context.Context, evt NoShowRecorded) error
}
```
