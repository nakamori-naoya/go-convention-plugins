# 複数集約の協調

**2 つ以上の集約に関わる業務イベントは、domain-model 資料「集約どうしの協働」の「一貫性」に従って形を選ぶ。「同じ操作」なら同じ tx で 2 集約を操作し、「結果整合」ならドメインイベントを受けた別の usecase が続ける。集約の外で守る不変条件は、材料を読み取りポートで読み、判定はドメインに呼ばせ、資料の sentinel を返す。** usecase が決めるのは形と順序であって、可否ではない。

## 1. どちらを選ぶか

| 資料の「一貫性」 | 形 | tx | 片方だけ成立したとき |
|---|---|---|---|
| 同じ操作 | 1 つの usecase が同じ `Run` の中で両方の集約を操作し、両方を保存する（§2） | 1 | 起きない。後の保存が失敗すれば前の保存も rollback される |
| 結果整合 | 起こす側の usecase が commit した後、ドメインイベントを受けて別の usecase が続ける（§3） | 2 | 起きる。資料「同時に起きたとき」と「集約どうしの協働」の決めに従って受ける側を書く。資料に無ければ書かずに返す |
| 値として渡す | 呼ぶ側が材料を集めて VO を導出し、集約の生成・操作の引数で渡す（§4） | 1 | 起きない。VO は保存されない |

| 「同じ操作」を選ぶ条件（全部を満たす） | 満たさなければ「結果整合」 |
|---|---|
| 資料が「同じ操作」と書いている | 資料が「結果整合」と書いている、または「同時に起きたとき」で先後を決めている |
| 同じ境界づけられたコンテキストで、同じ DB にある | 別のコンテキスト、別の DB、外部サービス |
| 片方だけ成立した状態を業務が許さない | 片方だけ成立した状態に業務上の名前がある（「取消は成立したが、繰上げはまだ」） |

資料に組が無いとき、usecase が「まとめて 1 tx にすれば安全」と決めない。同じ tx にすると、一方の拒否が他方を巻き込み、資料に無い順序と拒否が生まれる。組を資料へ返す。

題材（貸会議室予約）の「集約どうしの協働」:

| 集約 → 集約 | 資料の一貫性 | 形 |
|---|---|---|
| 予約 → 予約待ち（取消・期限到来が繰上げ判断を始める） | 結果整合。「取消の成立後に一件だけ」 | `CancelReservation` / `ExpireReservation` が commit → `CancelledEvent` / `ExpiredEvent` を受けて `PromoteWaitlist` が続ける（§3） |
| 予約待ち → 予約（繰上げ判断が「繰り上げる」の後に「仮押さえ予約を成立させる」を呼ぶ） | 呼び手が両方を操作。「片方だけ成立したときの扱いは未決」 | 未決のままなら停止条件。§2 の例は、未決が「同じ tx で一貫させる」と決まったと仮定して書く |
| 予約 → 顧客の予約資格 | 同じ操作。イベントを経由しない | `HoldReservation` が無断不利用の時刻を読み、`NewEligibility` で導出して `Hold` に渡す（§4） |

## 2. 同じ tx で 2 集約

1 つの `Run` の中で、資料「手段」の順に両方の集約を復元（または生成）→ 絞り込み → 操作 → 保存する。それぞれの集約の永続化ポート（イベント型なら `Apply{Event}`、通常型なら `Create` / `Update`）を同じ ctx で呼ぶ。

例で仮定する集約「予約待ち」（package `waitlist`。題材のデータモデル資料に無いので通常型）:

| 仮定 | 形 |
|---|---|
| 識別子 | `waitlist.ID`（`NewID(s string) (ID, error)`）、`waitlist.CustomerID`（`Value() string`） |
| 和型と状態型 | `waitlist.Waitlist`（封じた interface）。`Waiting`（予約待ち中）と `Ended`（繰上済み・取消済み） |
| 絞り込み | `waitlist.AsWaiting(w Waitlist) (Waiting, error)`。終了していれば `ErrWaitlistEnded` |
| 操作「繰り上げる」 | `(Waiting) Promote(at time.Time) (PromoteResult, bool)`。資料は「拒む理由: なし（予約待ち中でなければ何も変えない）」なので、拒まない操作の形 `(Result, bool)` |
| 永続化ポート | `waitlist.Repository`（`FindByID` / `Create` / `Update`） |
| 読み取りモデル | `query.WaitingEntry{WaitlistID string}` |

```go
package usecase

import (
	"context"
	"fmt"
	"time"

	query "example.com/roomflow/reservation/usecase/query"
	"example.com/roomflow/reservation"
	"example.com/roomflow/tx"
	"example.com/roomflow/waitlist"
)

// WaitingReader は空いた利用枠の予約待ち中を受付順（受付日時、予約待ち番号）で読む読み取りポート。並び順は SQL が決める。
type WaitingReader interface {
	ListWaitingBySlot(ctx context.Context, roomCode string, startsAt, endsAt time.Time) ([]query.WaitingEntry, error)
}

// PromoteWaitlist は「予約が取り消された」「仮押さえ期限が到来した」を受け、資料「導出されること」の手順で一件を繰り上げる。
// 予約待ち（通常型）と予約（イベント型）を同じ tx で操作する。
type PromoteWaitlist struct {
	tx           *tx.Manager
	waiting      WaitingReader
	waitlists    waitlist.Repository
	reservations reservation.Repository
	noShows      NoShowReader
	ids          IDGenerator
}

// PromoteWaitlistInput は空いた利用枠と繰上げの時刻。利用枠は受けたイベントの Slot() から作り、時刻は受ける側（配送の仕組み）が 1 回決める。
type PromoteWaitlistInput struct {
	RoomCode string
	StartsAt time.Time
	EndsAt   time.Time
	At       time.Time
}

func (u *PromoteWaitlist) Execute(ctx context.Context, in PromoteWaitlistInput) error {
	room, err := reservation.NewRoomCode(in.RoomCode)
	if err != nil {
		return fmt.Errorf("繰上げの入力: %w", err)
	}
	slot, err := reservation.NewTimeSlot(room, in.StartsAt, in.EndsAt)
	if err != nil {
		return fmt.Errorf("会議室 %s の繰上げの入力: %w", in.RoomCode, err)
	}
	id, err := u.ids.NewReservationID()
	if err != nil {
		return fmt.Errorf("会議室 %s の繰上げの採番: %w", in.RoomCode, err)
	}
	return u.tx.Run(ctx, func(ctx context.Context) error {
		candidates, err := u.waiting.ListWaitingBySlot(ctx, in.RoomCode, in.StartsAt, in.EndsAt)
		if err != nil {
			return fmt.Errorf("会議室 %s の予約待ちの取得: %w", in.RoomCode, err)
		}
		if len(candidates) == 0 {
			return nil // 資料「予約待ち中が一件も無ければ、利用枠は空いたままにする」
		}
		head := candidates[0] // 資料「先頭の一件を繰り上げ」。並び順は読み取りポートが資料の順で返す

		// 集約 1: 予約待ち（通常型）。復元 → 絞り込み → 操作 → 保存
		wid, err := waitlist.NewID(head.WaitlistID)
		if err != nil {
			return fmt.Errorf("予約待ち %s の繰上げ: %w", head.WaitlistID, err)
		}
		w, err := u.waitlists.FindByID(ctx, wid)
		if err != nil {
			return fmt.Errorf("予約待ち %s の繰上げ: %w", head.WaitlistID, err)
		}
		waiting, err := waitlist.AsWaiting(w)
		if err != nil {
			return fmt.Errorf("予約待ち %s の繰上げ: %w", head.WaitlistID, err)
		}
		promoted, ok := waiting.Promote(in.At)
		if !ok {
			return nil // 資料「予約待ち中でなければ何も変えない」。AsWaiting を通った後なので起きないが、bool を捨てない
		}
		if err := u.waitlists.Update(ctx, promoted.Next); err != nil {
			return fmt.Errorf("予約待ち %s の繰上げ: %w", head.WaitlistID, err)
		}

		// 集約 2: 予約（イベント型）。材料 → 生成 → 保存。重なり検査は HoldReservation と同じ手順（ここでは省く）
		customer, err := reservation.NewCustomerID(waiting.Customer().Value())
		if err != nil {
			return fmt.Errorf("予約待ち %s の繰上げ: %w", head.WaitlistID, err)
		}
		noShowAt, err := u.noShows.ListNoShowAt(ctx, customer.Value())
		if err != nil {
			return fmt.Errorf("顧客 %s の無断不利用の取得: %w", customer.Value(), err)
		}
		eligibility := reservation.NewEligibility(customer, noShowAt, in.At)
		res, err := reservation.Hold(id, customer, slot, eligibility, in.At)
		if err != nil {
			return fmt.Errorf("予約待ち %s の繰上げ: %w", head.WaitlistID, err)
		}
		if err := u.reservations.ApplyHeld(ctx, res.Event); err != nil {
			return fmt.Errorf("予約 %s の仮押さえ: %w", id.Value(), err)
		}
		return nil
	})
}
```

| する | しない | 理由 |
|---|---|---|
| 資料「手段」の順に操作する（繰り上げる → 仮押さえ予約を成立させる） | 保存しやすい順、失敗しにくい順に並べ替える | 順序は資料の決めで、rollback があるので失敗の順は問題にならない |
| 各集約に復元 → 絞り込み → 操作 → 保存を揃える | 集約 A の状態を見て集約 B の操作を選ぶ（`if _, ok := w.(waitlist.Ended); ok { ... }`） | 状態違いは `As*` が sentinel で返す。usecase は判断しない |
| 集約 A の getter を集約 B の材料にする（`waiting.Customer()` → `NewCustomerID`） | 集約 A を集約 B の引数に渡す | 集約は他の集約を持たない。渡すのは値 |
| `len(candidates) == 0` のような「対象が無い」分岐は資料の語でコメントする | 件数を業務の拒否にする（`len(x) > 0` で sentinel） | 「無ければ何もしない」は資料の手順。「あれば拒む」は集約の判断 |
| 先頭の予約待ちの顧客が停止中なら `Hold` の `ErrCustomerSuspended` で全体を rollback する | 次の候補へ進む | 資料に無い場面。usecase が手順を発明しない。要るなら資料へ返す |

## 3. ドメインイベントを受けて別の usecase が続ける

起こす側は自分の業務イベントを commit して終わる。受ける側は、起こす側が発したドメインイベントの値から Input を作って `Execute` される別の usecase で、別の tx に乗る。

```
CancelReservation.Execute ── commit ──▶ CancelledEvent ──（配送）──▶ PromoteWaitlist.Execute ── commit
        tx 1                                                                     tx 2
```

| usecase が決めること | 規則 | 理由 |
|---|---|---|
| 受ける側の Input | 受けるイベントの getter だけから作れる primitive（`evt.Slot().Room().Value()` / `evt.Slot().Start()` / `evt.Slot().End()`）と、受ける側が 1 回決める時刻 `At` | 配送の仕組みが何であれ（同じプロセスの dispatcher、イベント表を読む worker、メッセージング）、イベントの値だけで受ける側を呼べる。イベントに無い値が要るなら、それはイベントの規約（ドメイン）へ返す |
| 受ける側が走る時点 | 起こす側の commit 後 | commit 前に走ると、起こす側が rollback したときに「取り消されていない予約」の枠へ繰り上げてしまう |
| 受ける側の再実行 | 同じイベントを 2 回受けても、2 回目が二重に成立しない | 配送は 1 回以上を保証するものが多い。上の `PromoteWaitlist` は先頭の予約待ち中を読み直すので、1 回目で繰り上がった予約待ちは 2 回目の候補に無く、次の候補があっても `Hold` の保存が排他制約で `ErrOverlappingSlot` になって止まる |
| 片方だけ成立したときの扱い | 資料「同時に起きたとき」と「集約どうしの協働」に従う。題材では「取消は成立、繰上げは失敗」なら予約待ちは予約待ち中のまま、枠は空いたままで、イベントを再配送して繰上げをやり直す | 受ける側が失敗しても起こす側は取り消さない（補償を書かない）。資料が「取消の成立後に一件だけ」と決めている |
| 配送の仕組み | 決めない。上位の開発規約と永続化の規約の関心 | usecase が知るのは「イベントの値から Input を作る」ことだけ |

起こす側の usecase は、受ける側を呼ばない。`CancelReservation` の `Run` の中で `u.promote.Execute(...)` を呼ぶと、tx が入れ子になり、資料の「結果整合」が「同じ操作」に変わる。

## 4. 集約の外で守る不変条件と、値として渡す材料

資料「集約の境界」の「集約をまたぐ不変条件」は集約の内側では確かめられない。「守る場所」が「生成を呼ぶ側」なら、usecase が材料を読み取りポートで読み、判定はドメインの関数に呼ばせ、資料の sentinel を返す。DB 制約が最後の砦である。

| 不変条件 | 材料 | 判定 | 返す sentinel | 最後の砦 |
|---|---|---|---|---|
| 同じ会議室の重なる利用枠へ、現在有効な予約は一つ | `ActiveReservationReader.ListActiveOverlapping`（渡した利用枠と重なる現在有効な予約の利用枠） | `reservation.NewTimeSlot` で復元し `slot.Overlaps(existing)` | `reservation.ErrOverlappingSlot`（`Hold` を呼ばずに返す） | `room_booking_claims` の排他制約。リポジトリが同じ sentinel に翻訳する |

```go
		// HoldReservation.Execute の Run の中（command.md §3）
		active, err := u.active.ListActiveOverlapping(ctx, in.RoomCode, slot.Start(), slot.End())
		if err != nil {
			return fmt.Errorf("会議室 %s の有効な予約の取得: %w", in.RoomCode, err)
		}
		for _, a := range active {
			existing, err := reservation.NewTimeSlot(room, a.StartsAt, a.EndsAt)
			if err != nil {
				return fmt.Errorf("会議室 %s の有効な予約の復元: %w", in.RoomCode, err)
			}
			if slot.Overlaps(existing) {
				return fmt.Errorf("会議室 %s の仮押さえ: %w", in.RoomCode, reservation.ErrOverlappingSlot)
			}
		}
```

| する | しない | 理由 |
|---|---|---|
| 判定はドメインのメソッド（`Overlaps` / `CanApply`） | usecase で時刻や件数を比べる | 半開区間・30 日・3 回は資料の数で、置き場はドメイン 1 か所 |
| 事前の検査と DB 制約の翻訳が同じ sentinel を返す | 「事前に見つけた重なり」と「同時に起きた重なり」を別の sentinel にする | 利用者から見て同じ結果に 2 つの名前を付けない。境界の対応表は 1 行で足りる |
| DB 制約が資料の不変条件と対応していることを確かめる | 読み取り検査だけで守れたと考える | 「読んでから書く」あいだの他の tx は読み取りでは防げない。制約が無ければデータモデル資料へ返す（停止条件） |

資料「集約どうしの協働」の「値として渡す」（予約 → 顧客の予約資格）は、不変条件ではなく生成の条件の材料である。usecase が材料（その顧客の予約で起きた無断不利用の時刻）を読み、VO の生成関数（`NewEligibility`）で導出し、集約の生成（`Hold`）に渡す。

```go
		noShowAt, err := u.noShows.ListNoShowAt(ctx, in.CustomerID)
		if err != nil {
			return fmt.Errorf("顧客 %s の無断不利用の取得: %w", in.CustomerID, err)
		}
		eligibility := reservation.NewEligibility(customer, noShowAt, in.At)
		res, err := reservation.Hold(id, customer, slot, eligibility, in.At)
```

| する | しない | 理由 |
|---|---|---|
| 材料を読み、VO の生成関数に渡す | `if len(noShowAt) >= 3 { return ErrCustomerSuspended }` | 導出は資料「生成の条件」そのもので、`NewEligibility` が持つ。usecase に写すと 2 か所になる |
| 資格の顧客と予約者の一致は `Hold` に確かめさせる | usecase で `eligibility.Customer() == customer` を見る | 生成の条件は集約が確かめ、`ErrEligibilityMismatch` を返す |
| 判定時刻は集約に渡す `in.At` と同じ値 | 材料の読み取りと生成で別の時刻を使う。usecase が時計を持つ | 資格は「その時点」の値。時刻が 2 つあると資格と成立時刻がずれる |
