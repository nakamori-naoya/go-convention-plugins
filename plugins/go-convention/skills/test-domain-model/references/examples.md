# 完全な例 — `reservation_test.go`

資料「ドメインモデル — 貸会議室の予約」の集約「予約」を写した package `reservation` のテストのうち、`TestHold` / `TestTentative_Confirm` / `TestAsTentative` / `TestTimeSlot_Overlaps` の 4 本と末尾コメントを示す。**書き始める前に一度読み、この形を写す。** 割り振りの根拠は [mapping-from-doc.md](mapping-from-doc.md) §3、フィールドの形は [table-shape.md](table-shape.md)。

module は `example.com/roomflow`。ディレクトリ構成は上位の開発規約が決めるので、例は import path を短くするため平らに置いている。実際のファイルには `TestTentative_Cancel` / `TestConfirmed_Cancel` / `TestTentative_Expire` / `TestConfirmed_RecordNoShow` / `TestAsActive` / `TestHoldDeadline_HasArrived` / `TestEligibility_CanApply` / `TestNewTimeSlot` / `TestVersion_Next` も並び、資料の BDD-003 / 005 / 009 / 011 / 015 / 016 / 017 / 020 / 024 はそれらの `id:` にある。末尾コメントは完全な形で示すので、この抜粋に無い ID が末尾コメントに無いのはそのためである。

## テストが使う公開 API

```go
// 値オブジェクト
func NewID(s string) (ID, error)
func NewCustomerID(s string) (CustomerID, error)
func NewRoomCode(s string) (RoomCode, error)
func NewTimeSlot(room RoomCode, start, end time.Time) (TimeSlot, error) // start < end。UTC に正規化
func (s TimeSlot) Overlaps(o TimeSlot) bool                              // 半開区間。隣接は偽
func RestoreHoldDeadline(at time.Time) HoldDeadline
func (d HoldDeadline) At() time.Time
func NewEligibility(customer CustomerID, noShowAt []time.Time, at time.Time) Eligibility
func NewVersion(n int) (Version, error)
func (v Version) Next() Version
func (v Version) Value() int

// 集約: 生成・遷移・絞り込み・復元
func Hold(id ID, customer CustomerID, slot TimeSlot, eligibility Eligibility, at time.Time) (HoldResult, error)
func (t Tentative) Confirm(at time.Time, by CustomerID) (ConfirmResult, error)
func AsTentative(r Reservation) (Tentative, error)
func RestoreTentative(id ID, customer CustomerID, slot TimeSlot, deadline HoldDeadline, v Version) Tentative
func RestoreConfirmed(id ID, customer CustomerID, slot TimeSlot, noShowAt time.Time, v Version) Confirmed
func RestoreCancelled(id ID, customer CustomerID, slot TimeSlot, v Version) Cancelled
func RestoreExpired(id ID, customer CustomerID, slot TimeSlot, v Version) Expired

// 遷移結果型とイベント
type Transition[S Reservation, E Event] struct { Next S; Event E }
type HoldResult    = Transition[Tentative, Held]
type ConfirmResult = Transition[Confirmed, ConfirmedEvent]
func (e Held) ReservationID() ID
func (e Held) Version() Version
func (e Held) OccurredAt() time.Time
func (e Held) Customer() CustomerID
func (e Held) Slot() TimeSlot
func (e Held) Deadline() HoldDeadline
func (e ConfirmedEvent) ReservationID() ID
func (e ConfirmedEvent) Version() Version
func (e ConfirmedEvent) OccurredAt() time.Time
func (e ConfirmedEvent) By() CustomerID

// sentinel
var ErrCustomerSuspended, ErrEligibilityMismatch, ErrHoldDeadlinePassed, ErrAlreadyConfirmed, ErrNotOwner, ErrAlreadyCancelled, ErrAlreadyExpired, ErrNoReservation error
```

## コード

```go
package reservation_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/roomflow/reservation"
)

func TestHold(t *testing.T) {
	t.Parallel()

	// 表で使う値オブジェクト。資料の Given に現れない予約番号は全ケース同じ値を使う。
	reservationID, err := reservation.NewID("R-1")
	require.NoError(t, err)
	customer, err := reservation.NewCustomerID("C-1")
	require.NoError(t, err)
	other, err := reservation.NewCustomerID("C-2")
	require.NoError(t, err)
	room, err := reservation.NewRoomCode("large")
	require.NoError(t, err)
	slotSep18, err := reservation.NewTimeSlot(room, time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC), time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC))
	require.NoError(t, err)
	slotSep20, err := reservation.NewTimeSlot(room, time.Date(2026, 9, 20, 10, 0, 0, 0, time.UTC), time.Date(2026, 9, 20, 11, 0, 0, 0, time.UTC))
	require.NoError(t, err)
	slotOct3, err := reservation.NewTimeSlot(room, time.Date(2026, 10, 3, 10, 0, 0, 0, time.UTC), time.Date(2026, 10, 3, 11, 0, 0, 0, time.UTC))
	require.NoError(t, err)
	v1, err := reservation.NewVersion(1)
	require.NoError(t, err)

	// 直近 30 日で 3 回の無断不利用。3 回目の 2026-09-18 10:16 から 14 日間（2026-10-02 10:16 まで）が仮押さえ停止。
	threeNoShows := []time.Time{
		time.Date(2026, 9, 5, 10, 16, 0, 0, time.UTC),
		time.Date(2026, 9, 12, 10, 16, 0, 0, time.UTC),
		time.Date(2026, 9, 18, 10, 16, 0, 0, time.UTC),
	}

	// held は発したイベントの射影。型は HoldResult が決めているので、値だけを getter で並べて比べる。
	type held struct {
		reservationID reservation.ID
		version       int
		occurredAt    time.Time
		customer      reservation.CustomerID
		slot          reservation.TimeSlot
		deadline      time.Time
	}

	tests := []struct {
		id          string
		name        string
		description string
		customer    reservation.CustomerID  // Given: 予約者（Hold の引数名そのまま）
		slot        reservation.TimeSlot    // Given: 利用枠
		eligibility reservation.Eligibility // Given: 呼ぶ側が導出して渡す顧客の予約資格
		at          time.Time               // When:  成立時刻
		wantNext    reservation.Tentative   // Then:  Restore で組んだ仮押さえ予約
		wantEvent   held                    // Then:  仮押さえ予約が成立した の値
		wantErr     error                   // Then:  nil なら成功を期待
	}{
		{
			id:   "BDD-001",
			name: "空いている利用枠に仮押さえ予約が成立する",
			description: `Given: 予約可能顧客である予約者がいる
  And: 2026年9月18日 10:00から11:30までの大会議室に予約はない
When: その予約者が2026年9月18日 10:00から11:30までの大会議室を2026年9月1日 09:00に仮押さえする
Then: その予約者に2026年9月18日 10:00から11:30までの大会議室の仮押さえ予約が成立する
  And: 仮押さえ期限は2026年9月1日 09:15になる
  And: 2026年9月18日 10:00から11:30までの大会議室へ別の予約は成立しない`,
			customer:    customer,
			slot:        slotSep18,
			eligibility: reservation.NewEligibility(customer, nil, time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC)),
			at:          time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
			wantNext:    reservation.RestoreTentative(reservationID, customer, slotSep18, reservation.RestoreHoldDeadline(time.Date(2026, 9, 1, 9, 15, 0, 0, time.UTC)), v1),
			wantEvent: held{
				reservationID: reservationID,
				version:       1,
				occurredAt:    time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
				customer:      customer,
				slot:          slotSep18,
				deadline:      time.Date(2026, 9, 1, 9, 15, 0, 0, time.UTC),
			},
		},
		{
			id:   "BDD-010",
			name: "仮押さえ停止中の新しい仮押さえは成立しない",
			description: `Given: ある予約者は2026年10月2日 10:16まで仮押さえ停止中顧客である
  And: 2026年9月20日 10:00から11:00までの大会議室に予約はない
When: その予約者が2026年9月20日 10:00から11:00までの大会議室を2026年9月19日 09:00に仮押さえする
Then: 仮押さえ予約は成立しない
  And: 2026年9月20日 10:00から11:00までの大会議室は空いたままである
  NOTE: Rule: 仮押さえ停止中顧客は、新しい仮押さえ予約と予約待ちを申し込めない
    Reason: 申込みの時点が停止期間の内側にあり、新しい仮押さえ予約を成立させられないため`,
			customer:    customer,
			slot:        slotSep20,
			eligibility: reservation.NewEligibility(customer, threeNoShows, time.Date(2026, 9, 19, 9, 0, 0, 0, time.UTC)),
			at:          time.Date(2026, 9, 19, 9, 0, 0, 0, time.UTC),
			wantErr:     reservation.ErrCustomerSuspended,
		},
		{
			id:   "BDD-012",
			name: "停止期間の終了後に仮押さえ予約が成立する",
			description: `Given: ある予約者は2026年10月2日 10:16に予約可能顧客へ戻っている
  And: 2026年10月3日 10:00から11:00までの大会議室に予約はない
When: その予約者が2026年10月3日 10:00から11:00までの大会議室を2026年10月2日 10:17に仮押さえする
Then: その予約者に2026年10月3日 10:00から11:00までの大会議室の仮押さえ予約が成立する
  And: 仮押さえ期限は2026年10月2日 10:32になる`,
			customer:    customer,
			slot:        slotOct3,
			eligibility: reservation.NewEligibility(customer, threeNoShows, time.Date(2026, 10, 2, 10, 17, 0, 0, time.UTC)),
			at:          time.Date(2026, 10, 2, 10, 17, 0, 0, time.UTC),
			wantNext:    reservation.RestoreTentative(reservationID, customer, slotOct3, reservation.RestoreHoldDeadline(time.Date(2026, 10, 2, 10, 32, 0, 0, time.UTC)), v1),
			wantEvent: held{
				reservationID: reservationID,
				version:       1,
				occurredAt:    time.Date(2026, 10, 2, 10, 17, 0, 0, time.UTC),
				customer:      customer,
				slot:          slotOct3,
				deadline:      time.Date(2026, 10, 2, 10, 32, 0, 0, time.UTC),
			},
		},
		{
			id:   "1fbea5",
			name: "別の顧客の予約資格では仮押さえできない",
			description: `Given: 予約可能顧客である予約者がいる
  And: 渡された顧客の予約資格は別の顧客のものである
When: その予約者が2026年9月18日 10:00から11:30までの大会議室を2026年9月1日 09:00に仮押さえする
Then: 予約資格の顧客が予約者と一致しないため成立しない
  NOTE: Rule: 受け取った顧客の予約資格の顧客が予約者と同じであること
    Reason: 別の顧客の資格で予約者の申込み可否を決めると、資格の取り違えが生成で止まらないため`,
			customer:    customer,
			slot:        slotSep18,
			eligibility: reservation.NewEligibility(other, nil, time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC)),
			at:          time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
			wantErr:     reservation.ErrEligibilityMismatch,
		},
	}

	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			got, err := reservation.Hold(reservationID, tt.customer, tt.slot, tt.eligibility, tt.at)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.wantNext, got.Next)
			assert.Equal(t, tt.wantEvent, held{
				reservationID: got.Event.ReservationID(),
				version:       got.Event.Version().Value(),
				occurredAt:    got.Event.OccurredAt(),
				customer:      got.Event.Customer(),
				slot:          got.Event.Slot(),
				deadline:      got.Event.Deadline().At(),
			})
		})
	}
}

func TestTentative_Confirm(t *testing.T) {
	t.Parallel()

	// 表で使う値オブジェクト。資料の Given に現れない予約番号と版は全ケース同じ値を使う。
	reservationID, err := reservation.NewID("R-1")
	require.NoError(t, err)
	owner, err := reservation.NewCustomerID("C-1")
	require.NoError(t, err)
	other, err := reservation.NewCustomerID("C-2")
	require.NoError(t, err)
	room, err := reservation.NewRoomCode("large")
	require.NoError(t, err)
	slot, err := reservation.NewTimeSlot(room, time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC), time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC))
	require.NoError(t, err)
	v1, err := reservation.NewVersion(1)
	require.NoError(t, err)

	// confirmed は発したイベントの射影。型は ConfirmResult が決めているので、値だけを getter で並べて比べる。
	type confirmed struct {
		reservationID reservation.ID
		version       int
		occurredAt    time.Time
		by            reservation.CustomerID
	}

	tests := []struct {
		id          string
		name        string
		description string
		customer    reservation.CustomerID   // Given: 予約者（RestoreTentative の引数名そのまま）
		slot        reservation.TimeSlot     // Given: 利用枠
		deadline    reservation.HoldDeadline // Given: 仮押さえ期限
		at          time.Time                // When:  確定時刻
		by          reservation.CustomerID   // When:  呼び手
		wantNext    reservation.Confirmed    // Then:  Restore で組んだ確定予約。版だけ進む
		wantEvent   confirmed                // Then:  予約が確定した の値
		wantErr     error                    // Then:  nil なら成功を期待
	}{
		{
			id:   "BDD-002",
			name: "仮押さえ期限より前の確定で確定予約になる",
			description: `Given: ある予約者の仮押さえ予約がある
  And: 利用枠は2026年9月18日 10:00から11:30までの大会議室である
  And: 仮押さえ期限は2026年9月1日 09:15である
When: その予約者が2026年9月1日 09:14に予約を確定する
Then: その予約は確定予約になる
  And: 仮押さえ期限は役割を終える
  And: 確定予約の利用枠は2026年9月18日 10:00から11:30までの大会議室のままである`,
			customer: owner,
			slot:     slot,
			deadline: reservation.RestoreHoldDeadline(time.Date(2026, 9, 1, 9, 15, 0, 0, time.UTC)),
			at:       time.Date(2026, 9, 1, 9, 14, 0, 0, time.UTC),
			by:       owner,
			wantNext: reservation.RestoreConfirmed(reservationID, owner, slot, time.Time{}, v1.Next()),
			wantEvent: confirmed{
				reservationID: reservationID,
				version:       2,
				occurredAt:    time.Date(2026, 9, 1, 9, 14, 0, 0, time.UTC),
				by:            owner,
			},
		},
		{
			id:   "e68774",
			name: "仮押さえ期限と同時刻の確定は拒まれる",
			description: `Given: ある予約者の仮押さえ予約がある
  And: 仮押さえ期限は2026年9月1日 09:15である
When: その予約者が2026年9月1日 09:15に予約を確定する
Then: 仮押さえ期限以降のため確定できない
  NOTE: Rule: 確定予約は仮押さえ期限より前にだけ成立し、仮押さえ期限と同時の確定では期限の到来を先に扱う
    Reason: 確定の時刻が仮押さえ期限と同じで、確定できる期間に含まれないため`,
			customer: owner,
			slot:     slot,
			deadline: reservation.RestoreHoldDeadline(time.Date(2026, 9, 1, 9, 15, 0, 0, time.UTC)),
			at:       time.Date(2026, 9, 1, 9, 15, 0, 0, time.UTC),
			by:       owner,
			wantErr:  reservation.ErrHoldDeadlinePassed,
		},
		{
			id:   "ebe53b",
			name: "第三者は仮押さえ予約を確定できない",
			description: `Given: ある予約者の仮押さえ予約がある
  And: 仮押さえ期限は2026年9月1日 09:15である
  And: 別の予約者がいる
When: 別の予約者が2026年9月1日 09:14にその予約を確定する
Then: 他人の予約のため確定できない
  NOTE: Rule: 仮押さえ予約を確定できるのはその予約の予約者である
    Reason: 第三者は本人の利用意思を示せないため`,
			customer: owner,
			slot:     slot,
			deadline: reservation.RestoreHoldDeadline(time.Date(2026, 9, 1, 9, 15, 0, 0, time.UTC)),
			at:       time.Date(2026, 9, 1, 9, 14, 0, 0, time.UTC),
			by:       other,
			wantErr:  reservation.ErrNotOwner,
		},
		{
			id:   "fa6fdd",
			name: "期限以降かつ第三者の確定は期限の理由で拒まれる",
			description: `Given: ある予約者の仮押さえ予約がある
  And: 仮押さえ期限は2026年9月1日 09:15である
  And: 別の予約者がいる
When: 別の予約者が2026年9月1日 09:20にその予約を確定する
Then: 仮押さえ期限以降のため確定できない
  NOTE: Rule: 事前条件は資料の順に確かめ、期限の到来を呼び手の照合より先に扱う
    Reason: 二つの事前条件を同時に破っていて、最初に当たる理由が返るため`,
			customer: owner,
			slot:     slot,
			deadline: reservation.RestoreHoldDeadline(time.Date(2026, 9, 1, 9, 15, 0, 0, time.UTC)),
			at:       time.Date(2026, 9, 1, 9, 20, 0, 0, time.UTC),
			by:       other,
			wantErr:  reservation.ErrHoldDeadlinePassed,
		},
	}

	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			tentative := reservation.RestoreTentative(reservationID, tt.customer, tt.slot, tt.deadline, v1)

			got, err := tentative.Confirm(tt.at, tt.by)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.wantNext, got.Next)
			assert.Equal(t, tt.wantEvent, confirmed{
				reservationID: got.Event.ReservationID(),
				version:       got.Event.Version().Value(),
				occurredAt:    got.Event.OccurredAt(),
				by:            got.Event.By(),
			})
		})
	}
}

func TestAsTentative(t *testing.T) {
	t.Parallel()

	// 表で使う値オブジェクト。絞り込みは状態だけを見るので、予約番号・予約者・利用枠・版は全ケース同じ値を使う。
	reservationID, err := reservation.NewID("R-1")
	require.NoError(t, err)
	owner, err := reservation.NewCustomerID("C-1")
	require.NoError(t, err)
	room, err := reservation.NewRoomCode("large")
	require.NoError(t, err)
	slot, err := reservation.NewTimeSlot(room, time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC), time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC))
	require.NoError(t, err)
	v1, err := reservation.NewVersion(1)
	require.NoError(t, err)
	deadline := reservation.RestoreHoldDeadline(time.Date(2026, 9, 1, 9, 15, 0, 0, time.UTC))

	tests := []struct {
		id          string
		name        string
		description string
		r           reservation.Reservation // Given: 和型の値（AsTentative の引数名そのまま）。Restore* で組む
		want        reservation.Tentative   // Then:  絞り込めたときの値
		wantErr     error                   // Then:  nil なら成功を期待
	}{
		{
			id:   "BDD-023",
			name: "確定済み予約の再確定は新しい予約を生まない",
			description: `Given: ある予約者の確定予約がある
  And: 利用枠は2026年9月18日 10:00から11:30までの大会議室である
When: その予約者が同じ予約を再び確定する
Then: その予約は同じ確定予約のままである
  And: 新しい確定予約は成立しない
  And: 2026年9月18日 10:00から11:30までの大会議室の占有は一件のままである
  NOTE: Rule: 確定済み予約の再確定は拒む
    Reason: 利用意思はすでに示されており、確定予約が成立しているため`,
			r:       reservation.RestoreConfirmed(reservationID, owner, slot, time.Time{}, v1.Next()),
			wantErr: reservation.ErrAlreadyConfirmed,
		},
		{
			id:   "5dee09",
			name: "仮押さえ予約はそのまま仮押さえ予約として扱える",
			description: `Given: ある予約者の仮押さえ予約がある
When: 仮押さえ予約として絞り込む
Then: 同じ仮押さえ予約が返る`,
			r:    reservation.RestoreTentative(reservationID, owner, slot, deadline, v1),
			want: reservation.RestoreTentative(reservationID, owner, slot, deadline, v1),
		},
		{
			id:   "27d2e1",
			name: "取消済み予約は仮押さえ予約として扱えない",
			description: `Given: ある予約者の取消済み予約がある
When: 仮押さえ予約として絞り込む
Then: 取消済みのため操作できない
  NOTE: Rule: 取消済み予約と期限切れ予約は元の状態へ戻らない
    Reason: 終端状態の予約を仮押さえ予約として扱うと、解放済みの利用枠へ古い予約が復活するため`,
			r:       reservation.RestoreCancelled(reservationID, owner, slot, v1.Next()),
			wantErr: reservation.ErrAlreadyCancelled,
		},
		{
			id:   "05edaa",
			name: "期限切れ予約は仮押さえ予約として扱えない",
			description: `Given: ある予約者の期限切れ予約がある
When: 仮押さえ予約として絞り込む
Then: 期限切れのため操作できない
  NOTE: Rule: 取消済み予約と期限切れ予約は元の状態へ戻らない
    Reason: 終端状態の予約を仮押さえ予約として扱うと、解放済みの利用枠へ古い予約が復活するため`,
			r:       reservation.RestoreExpired(reservationID, owner, slot, v1.Next()),
			wantErr: reservation.ErrAlreadyExpired,
		},
		{
			id:   "c4ffea",
			name: "予約が無ければ絞り込めない",
			description: `Given: 予約が無い
When: 仮押さえ予約として絞り込む
Then: 予約が無いため絞り込めない`,
			wantErr: reservation.ErrNoReservation,
		},
	}

	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			got, err := reservation.AsTentative(tt.r)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestTimeSlot_Overlaps(t *testing.T) {
	t.Parallel()

	// 表で使う値オブジェクト。利用枠は New の引数（会議室・利用開始・利用終了）を表に置き、ループ本体で組む。
	large, err := reservation.NewRoomCode("large")
	require.NoError(t, err)
	small, err := reservation.NewRoomCode("small")
	require.NoError(t, err)

	tests := []struct {
		id          string
		name        string
		description string
		room        reservation.RoomCode // Given: 既存の予約の会議室
		start       time.Time            // Given: 既存の予約の利用開始
		end         time.Time            // Given: 既存の予約の利用終了
		oRoom       reservation.RoomCode // When:  比較相手（仮押さえしようとする利用枠）の会議室
		oStart      time.Time            // When
		oEnd        time.Time            // When
		want        bool                 // Then:  重なるか
	}{
		{
			id:   "BDD-013",
			name: "隣接する利用枠に仮押さえ予約が成立する",
			description: `Given: 予約可能顧客である予約者がいる
  And: 大会議室には2026年9月18日 10:00から11:00までの確定予約がある
  And: 大会議室の2026年9月18日 11:00から12:00までの利用枠に予約はない
When: その予約者が2026年9月18日 11:00から12:00までの大会議室を仮押さえする
Then: その予約者に大会議室の2026年9月18日 11:00から12:00までの仮押さえ予約が成立する
  And: 大会議室の2026年9月18日 10:00から11:00までの確定予約も維持される`,
			room:   large,
			start:  time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC),
			end:    time.Date(2026, 9, 18, 11, 0, 0, 0, time.UTC),
			oRoom:  large,
			oStart: time.Date(2026, 9, 18, 11, 0, 0, 0, time.UTC),
			oEnd:   time.Date(2026, 9, 18, 12, 0, 0, 0, time.UTC),
			want:   false,
		},
		{
			id:   "BDD-014",
			name: "一部でも重なる利用枠の仮押さえは成立しない",
			description: `Given: 予約可能顧客である予約者がいる
  And: 大会議室には2026年9月18日 10:00から11:00までの確定予約がある
When: その予約者が2026年9月18日 10:30から11:30までの大会議室を仮押さえする
Then: その予約者の仮押さえ予約は成立しない
  And: 大会議室の2026年9月18日 10:00から11:00までの確定予約は維持される
  NOTE: Rule: 同じ会議室の重なる利用枠へ、現在有効な予約は一つしか存在しない
    Reason: 10:30から11:00までが既存の確定予約と重なっており、二件目の有効な予約になるため`,
			room:   large,
			start:  time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC),
			end:    time.Date(2026, 9, 18, 11, 0, 0, 0, time.UTC),
			oRoom:  large,
			oStart: time.Date(2026, 9, 18, 10, 30, 0, 0, time.UTC),
			oEnd:   time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC),
			want:   true,
		},
		{
			id:   "4c0910",
			name: "別の会議室の同じ時間帯は重ならない",
			description: `Given: 大会議室には2026年9月18日 10:00から11:00までの確定予約がある
When: 2026年9月18日 10:00から11:00までの小会議室を仮押さえする
Then: 会議室が違うので重ならない`,
			room:   large,
			start:  time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC),
			end:    time.Date(2026, 9, 18, 11, 0, 0, 0, time.UTC),
			oRoom:  small,
			oStart: time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC),
			oEnd:   time.Date(2026, 9, 18, 11, 0, 0, 0, time.UTC),
			want:   false,
		},
		{
			id:   "c645a4",
			name: "先に始まって既存の利用開始をまたぐ利用枠は重なる",
			description: `Given: 大会議室には2026年9月18日 10:00から11:00までの確定予約がある
When: 2026年9月18日 09:30から10:30までの大会議室を仮押さえする
Then: 10:00から10:30までが重なる`,
			room:   large,
			start:  time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC),
			end:    time.Date(2026, 9, 18, 11, 0, 0, 0, time.UTC),
			oRoom:  large,
			oStart: time.Date(2026, 9, 18, 9, 30, 0, 0, time.UTC),
			oEnd:   time.Date(2026, 9, 18, 10, 30, 0, 0, time.UTC),
			want:   true,
		},
		{
			id:   "1f7379",
			name: "既存の利用枠の直前で終わる利用枠は重ならない",
			description: `Given: 大会議室には2026年9月18日 10:00から11:00までの確定予約がある
When: 2026年9月18日 09:00から10:00までの大会議室を仮押さえする
Then: 利用終了と既存の利用開始が同じ時刻なので重ならない`,
			room:   large,
			start:  time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC),
			end:    time.Date(2026, 9, 18, 11, 0, 0, 0, time.UTC),
			oRoom:  large,
			oStart: time.Date(2026, 9, 18, 9, 0, 0, 0, time.UTC),
			oEnd:   time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC),
			want:   false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			s, err := reservation.NewTimeSlot(tt.room, tt.start, tt.end)
			require.NoError(t, err)
			o, err := reservation.NewTimeSlot(tt.oRoom, tt.oStart, tt.oEnd)
			require.NoError(t, err)

			assert.Equal(t, tt.want, s.Overlaps(o))
		})
	}
}

// テストしない BDD:
// BDD-004 二人の同時仮押さえは集約をまたぐ排他で、メモリ上の値では再現できない。永続化層が対象
// BDD-006 予約待ちの登録は別の集約（予約待ち）の package が対象
// BDD-007 予約待ちの繰上げは別の集約（予約待ち）の package が対象。後半の仮押さえ成立は繰上げ判断（usecase）の責務
// BDD-008 予約待ちの取消は別の集約（予約待ち）の package が対象
// BDD-018 空いている利用枠への予約待ちは別の集約（予約待ち）の package が対象
// BDD-019 繰上げ順は繰上げ判断（usecase）の責務。繰り上げる操作は別の集約（予約待ち）の package が対象
// BDD-021 予約待ちの取消が先に成立する競合は別の集約（予約待ち）の package が対象
// BDD-022 予約待ちの繰上げが先に成立する競合は別の集約（予約待ち）の package が対象
```

## 読み方

| 見どころ | どこ |
|---|---|
| 生成関数の Given は引数のうち資料の `Given:` に写るもの、When は時刻 | `TestHold` の `customer` / `slot` / `eligibility` と `at` |
| `wantNext` を `Restore*` で Given と同じ値から組み、期限は `RestoreHoldDeadline` で | `TestHold` BDD-001 の `wantNext` |
| イベントは射影 struct で値だけを比べ、版は `wantNext` の版と同じ数 | `held` / `confirmed` と `version: 1` / `version: 2` |
| 拒むケースは `wantErr` だけを持ち、`assert.Zero` で結果がゼロ値であることも見る | BDD-010、`1fbea5`、`e68774` |
| 事前条件の順は、2 つ同時に破るケースで最初の理由が返ることで確かめる | `TestTentative_Confirm` の `fa6fdd` |
| 資料が VO に置いた境界（BDD-015）の集約側の結果は生成 id で | `TestTentative_Confirm` の `e68774` |
| 状態違いの拒否は絞り込み関数のテストに置く。`nil` も 1 ケース | `TestAsTentative` |
| VO のテストは `New*` の引数を表に置き、ループ本体で組む | `TestTimeSlot_Overlaps` |
| `description` の `Then:` に永続化の観測（別の予約は成立しない・占有は一件のまま）があっても削らない。報告に「永続化層が観測する」と書く | BDD-001 / BDD-023 |
| 末尾コメントは集約ルートのファイルに 1 つ。理由は「どの package・どの層が担うか」か「再現できない」 | ファイル末尾 |
