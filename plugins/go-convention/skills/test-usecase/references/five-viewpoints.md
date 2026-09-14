# 5 観点 — usecase で何をテストし、何をテストしないか

**usecase のテストは、usecase が持つ配線を 5 つの観点に分け、観点ごとの分岐の数だけケースを書く。** usecase は「入力を解決し、事実を集め、集約の操作を呼び、結果を保存する」薄い層で、業務判断を持たない。だからテストは「判断が正しいか」ではなく「正しいものを、正しい順で、正しい境界の中で呼んだか」を見る。

## 1. usecase のテストとは何か／何でないか

| usecase のテストである | usecase のテストではない |
|---|---|
| `Execute` を実 DB・実リポジトリ・実 tx・実 query service で通し、DB の状態と返り値で配線を確かめる | 業務ルールの網羅。VO の生成の条件、集約の事前条件・拒む理由・状態遷移はドメイン層のテストが資料の BDD で網羅済み |
| 入力の primitive がどの VO に写り、拒まれたらそのまま返ること | VO が何を拒むか（空・順序・境界値）。1 つの入力で「拒まれたらリポジトリに届かない」を見れば足りる |
| 別の集約（別のインスタンス）のどの行を読み、その結果で何が変わったか | 集約が持つ不変条件の検証。読んだ事実を集約がどう判断するかはドメイン層 |
| `tx.Manager.Run` の中が全成功か全未反映か | `Apply*` が全テーブルに正しく書くか。永続化層のテストが全テーブル全行で突き合わせ済み |
| 復元 → 絞り込み → 操作 → 保存の配線。どの `Apply*` が呼ばれたかをイベント表の行で見る。`(Result, bool)` の false が no-op になっていること | 呼び出し回数・引数・順序の interaction test。偽物のリポジトリで `Apply*` が呼ばれたかを数えない |
| query usecase が入力の解決結果を query service に渡し、DTO をそのまま返すこと | query service の SQL（JOIN / WHERE / 並び順）。永続化層のテストが Before → 読み取り → DTO で見る |

## 2. 5 観点

| # | 観点 | 何を見るか | 見る場所 | 題材での例 |
|---|---|---|---|---|
| 1 | 入力解決 | 入力の string / time を VO や範囲に写し、拒まれたら丸めずにそのまま返してリポジトリに届かない。「対象期間 → 範囲」「予約番号 → `ID`」のように、どの基盤データをどう採用したか | `wantErr`（VO の sentinel）と、変わらない `want{Table}` | `ConfirmReservation`: 空の予約番号 → `reservation.ErrIDRequired`。届いていれば `rdb.ErrNotFound` になるので区別できる |
| 2 | 複数集約の協調 | ある集約の操作が、別の集約（または同じ集約の別のインスタンス）のどの状態を読み、何を参照・変更したか。片方の集約のテストでは見えない | 読まれる側の `seed{Table}` と、変わる側の `want{Table}` | `HoldReservation`: 同じ顧客の他の予約の無断不利用から資格を導く。同じ会議室の占有中の利用枠と重なりを検査する |
| 3 | ソース選択（query） | 入力の状態で読む先が変わる分岐。進行中 → 現行の表、終了 → 履歴の表 | 両方のソースに `seed` を置き、選ばれた側の DTO が `want` | 題材は現行の予約だけを持つので 0 ケース |
| 4 | トランザクション境界 | `Run` の中が全成功（commit 後に全部見える）か全未反映（途中失敗で 1 行も変わらない）か | 成功ケースの `want{Table}` と、途中失敗ケースの `want{Table}` が前提と同じであること | `ConfirmReservation`: 基底イベントの一意制約で保存の 3 手目が失敗 → `reservations` が version 1 の仮押さえのまま |
| 5 | コマンド呼び分けと永続化 | 復元 → 絞り込み → 操作 → 保存の配線。どの `Apply*` / `Create` / `Update` が呼ばれたか。絞り込みや操作が拒んだら保存しない。`(Result, bool)` の false は `Apply*` を呼ばず nil を返す | `want{Table}`（current 行の状態と、イベント表の行） | `ConfirmReservation`: 仮押さえ → `confirmed` の行と確定イベント 1 行。確定済み → `ErrAlreadyConfirmed` で行は変わらない |

観点 4 の commit 側は、観点 5 の成功ケースが兼ねる。1 つのケースが 2 つの観点を兼ねてよい。兼ねられないのは rollback 側（途中失敗）で、これは必ず独立したケースにする。

## 3. 書かない観点

| 書かない | 誰の責務か | 理由 |
|---|---|---|
| VO の制約・境界値（利用終了が利用開始より前、期限と同時刻、隣接する利用枠） | ドメイン層のテスト（VO の生成の条件と操作） | usecase は VO の `New*` を呼ぶだけ。境界値を usecase で変えても、見えるのは同じ sentinel の素通し |
| 集約の不変条件・状態遷移（本人以外の確定、終端状態からの操作、期限到来後の確定） | ドメイン層のテスト（状態型のメソッドと絞り込み関数） | usecase は `AsTentative` と `Confirm` を呼ぶだけ。拒む理由の網羅はドメイン層が資料の BDD で済ませている |
| SQL の JOIN / WHERE / 並び順 / NULL の扱い | 永続化層のテスト（query service） | usecase は解決した入力を渡すだけ。渡った後の SQL は Before → 読み取り → DTO の突き合わせが見る |
| 全テーブル・全カラムの突き合わせ、イベント表の連結、楽観ロック競合、DB 制約の翻訳 | 永続化層のテスト（リポジトリ） | usecase は `Apply*` を呼ぶだけ。`Apply*` がどのテーブルに何を書くかは、永続化層が毎ケース全テーブル全行で見る |
| proto ↔ Input の変換 | handler のテスト | usecase の入口は Go の struct。proto は handler の関心 |
| sentinel → `connect.Code` の翻訳 | handler のテスト（interceptor） | usecase は sentinel を返すだけ。Code の対応表は境界 1 か所 |
| 認可（誰が呼べるか） | handler のテスト（interceptor） | usecase は主体を引数で受けるだけ。認可の判定は入口の関心 |
| ログが出たか | どの層のテストでも見ない | ログは最外境界が返った error から 1 回出す。usecase は error を返すだけ |

書きたくなったら、この表で責務の層を確かめ、その層のテストに足す。usecase に足さない。

## 4. 厚さの目安

| 観点 | ケース数 | 数え方 |
|---|---|---|
| 入力解決 | 1〜2 | 「拒まれたらリポジトリに届かない」を 1 つ。期間 → 範囲のような解決があれば、採用した基盤データが分かる 1 つ |
| 複数集約の協調 | 1〜3 | 読む相手の集約ごとに、読んだ事実で結果が変わる 1 つと、変わらない（他人の事実は数えない）1 つ |
| ソース選択 | 0〜3 | 読む先が分かれる入力の状態の数。分かれなければ 0 |
| tx 境界 | 2 | commit 1（成功ケースが兼ねる）と rollback 1（途中失敗） |
| 呼び分け | 1〜2 | 成功の配線 1 つ。絞り込みか操作が拒んで保存に進まない経路を 1 つ（状態ごとに増やさない）。`(Result, bool)` を呼ぶなら false の no-op を 1 つ |

**同じルールで入力値だけ変えるケースは書かない。** 「期限の 1 分前」「期限と同時刻」「期限の 1 分後」は仮押さえ期限の境界値であり、ドメイン層の責務である。usecase では「期限前に確定できる」の 1 つで配線が確かめられている。

題材の数: `ConfirmReservation` は 4 ケース（入力解決 1、呼び分け 2、rollback 1。commit は呼び分けの成功ケースが兼ねる）、`HoldReservation` は 3 ケース（協調 3。うち 1 つが成功で commit を兼ねる）。

## 5. 題材の usecase

テストが前提にする usecase の形。ID は usecase が `IDGenerator` で用意し、時刻は入力の `At`（RPC を受け取った境界が決める）で受けて集約へ渡す。usecase は `Clock` を持たない。読み取り（一覧・件数）は usecase 側の読み取りポートで、リポジトリには置かず、実装は query service の型が満たす。

```go
package usecase

import (
	"context"
	"fmt"
	"time"

	"example.com/roomflow/query"
	"example.com/roomflow/reservation"
	"example.com/roomflow/tx"
)

// IDGenerator は予約番号の採番。usecase が定義し（interface は使う側で定義）、実装は組み立てで注入する。
// ドメインは採番も time.Now() もしない。時刻は Input の At で受ける。
type IDGenerator interface {
	NewReservationID() (reservation.ID, error)
}

// ---- ConfirmReservation ----

type ConfirmReservation struct {
	tx   *tx.Manager
	repo reservation.Repository
}

func NewConfirmReservation(m *tx.Manager, repo reservation.Repository) *ConfirmReservation {
	return &ConfirmReservation{tx: m, repo: repo}
}

type ConfirmReservationInput struct {
	ReservationID string
	CustomerID    string
	At            time.Time
}

// Execute は 入力解決 → Run の中で 復元 → 絞り込み → 操作 → 保存。文脈は return ごとに 1 回足す。
func (u *ConfirmReservation) Execute(ctx context.Context, in ConfirmReservationInput) error {
	id, err := reservation.NewID(in.ReservationID)
	if err != nil {
		return fmt.Errorf("予約の確定の入力: %w", err)
	}
	by, err := reservation.NewCustomerID(in.CustomerID)
	if err != nil {
		return fmt.Errorf("予約 %s の確定の入力: %w", in.ReservationID, err)
	}
	return u.tx.Run(ctx, func(ctx context.Context) error {
		r, err := u.repo.FindByID(ctx, id)
		if err != nil {
			return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
		}
		t, err := reservation.AsTentative(r)
		if err != nil {
			return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
		}
		res, err := t.Confirm(in.At, by)
		if err != nil {
			return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
		}
		if err := u.repo.ApplyConfirmed(ctx, res.Event); err != nil {
			return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
		}
		return nil
	})
}

// ---- HoldReservation ----

// ActiveReservationReader は「同じ会議室の重なる利用枠に有効な予約が無い」を確かめる材料を読む読み取りポート。
// 行を読み取りモデルへ写すだけで、集約を復元しない。
type ActiveReservationReader interface {
	// ListActiveOverlapping は会議室の、[startsAt, endsAt) と重なる現在有効な予約の利用枠を返す。
	ListActiveOverlapping(ctx context.Context, roomCode string, startsAt, endsAt time.Time) ([]query.ActiveSlot, error)
}

// NoShowReader は顧客の予約資格を導く材料（その顧客の予約で起きた無断不利用の時刻）を読む読み取りポート。
type NoShowReader interface {
	ListNoShowAt(ctx context.Context, customerCode string) ([]time.Time, error)
}

type HoldReservation struct {
	tx      *tx.Manager
	repo    reservation.Repository
	active  ActiveReservationReader
	noShows NoShowReader
	ids     IDGenerator
}

func NewHoldReservation(m *tx.Manager, repo reservation.Repository, active ActiveReservationReader, noShows NoShowReader, ids IDGenerator) *HoldReservation {
	return &HoldReservation{tx: m, repo: repo, active: active, noShows: noShows, ids: ids}
}

type HoldReservationInput struct {
	CustomerID string
	RoomCode   string
	StartsAt   time.Time
	EndsAt     time.Time
	At         time.Time
}

type HoldReservationOutput struct {
	ReservationID string
	ExpiresAt     time.Time
}

// Execute は 入力解決 → ID の用意 → Run の中で 材料の収集（協調）→ 重なりの検査 → 資格の導出 → 生成 → 保存。
func (u *HoldReservation) Execute(ctx context.Context, in HoldReservationInput) (HoldReservationOutput, error) {
	customer, err := reservation.NewCustomerID(in.CustomerID)
	if err != nil {
		return HoldReservationOutput{}, fmt.Errorf("仮押さえの入力: %w", err)
	}
	room, err := reservation.NewRoomCode(in.RoomCode)
	if err != nil {
		return HoldReservationOutput{}, fmt.Errorf("仮押さえの入力: %w", err)
	}
	slot, err := reservation.NewTimeSlot(room, in.StartsAt, in.EndsAt)
	if err != nil {
		return HoldReservationOutput{}, fmt.Errorf("会議室 %s の仮押さえの入力: %w", in.RoomCode, err)
	}
	id, err := u.ids.NewReservationID()
	if err != nil {
		return HoldReservationOutput{}, fmt.Errorf("会議室 %s の仮押さえの採番: %w", in.RoomCode, err)
	}

	var out HoldReservationOutput
	err = u.tx.Run(ctx, func(ctx context.Context) error {
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
		noShowAt, err := u.noShows.ListNoShowAt(ctx, in.CustomerID)
		if err != nil {
			return fmt.Errorf("顧客 %s の無断不利用の取得: %w", in.CustomerID, err)
		}
		eligibility := reservation.NewEligibility(customer, noShowAt, in.At)
		res, err := reservation.Hold(id, customer, slot, eligibility, in.At)
		if err != nil {
			return fmt.Errorf("会議室 %s の仮押さえ: %w", in.RoomCode, err)
		}
		if err := u.repo.ApplyHeld(ctx, res.Event); err != nil {
			return fmt.Errorf("予約 %s の仮押さえ: %w", id.Value(), err)
		}
		out = HoldReservationOutput{ReservationID: id.Value(), ExpiresAt: res.Next.Deadline().At()}
		return nil
	})
	if err != nil {
		return HoldReservationOutput{}, err
	}
	return out, nil
}
```

`Execute` の各行を観点に割り当てると、テストのケースが決まる。

| `Execute` の行 | 観点 | ケース |
|---|---|---|
| `reservation.NewID(in.ReservationID)` が拒んだら返す | 1 入力解決 | 空の予約番号 → `ErrIDRequired`、行は変わらない |
| `ListNoShowAt` → `NewEligibility` → `Hold` | 2 協調 | 同じ顧客の無断不利用が 3 回 → `ErrCustomerSuspended`。他の顧客の 3 回 → 成立 |
| `ListActiveOverlapping` → `Overlaps` | 2 協調 | 占有中の利用枠と重なる → `ErrOverlappingSlot`、行は増えない |
| `u.tx.Run(...)` | 4 tx 境界 | 成功 → 行が見える。保存の途中失敗 → 行が前提のまま |
| `FindByID` → `AsTentative` → `Confirm` → `ApplyConfirmed` | 5 呼び分け | 仮押さえ → `confirmed` と確定イベント 1 行。確定済み → `ErrAlreadyConfirmed` で行は変わらない |

## 6. 観点ごとの書き方

完全なテストは [table-shape.md](table-shape.md) §5 にある。ここでは観点ごとに、何を Given に置き、何を Then で見るかを決める。

### 6.1 入力解決

- Given: 入力が正しければ成功する前提の行（`seedReservations` に仮押さえ予約）。届いたら結果が変わる前提を置くことで、「届かなかった」を状態で言える
- When: 1 つの入力だけを不正にする（`ReservationID: ""`）
- Then: `wantErr` は VO の sentinel（`reservation.ErrIDRequired`）。`rdb.ErrNotFound` ではないことが「リポジトリに届いていない」の証拠。`want{Table}` は前提と同じ
- 書くのは 1 ケース。`CustomerID: ""` を別ケースにしない（同じ配線の別の入力）

期間 → 範囲のような解決がある usecase では、解決結果によって読まれる行が変わる前提（範囲の内と外に 1 行ずつ）を置き、内側だけが結果に現れることを `want` で見る。

### 6.2 複数集約の協調

- Given: 読まれる側の行（同じ顧客の予約の無断不利用イベント。基底イベント `reservation_base_events` の `no_show_recorded` 行と、詳細イベント表 `reservation_no_show_recorded_events` の行。同じ会議室の `room_booking_claims`）。読まれない側の行（他の顧客・他の会議室）も 1 つ置き、区別されることを見る
- When: 操作する側の入力
- Then: 読んだ事実で結果が変わる（`wantErr: reservation.ErrCustomerSuspended`）、または変わらない（成立して行が増える）。変わる側の `want{Table}` に、読まれた側の行がそのまま残っていることも含める
- 資格の導出そのもの（30 日・3 回・14 日）はドメイン層の `NewEligibility` のテストが見る。ここでは「その顧客の記録だけが渡った」ことが分かる 2 ケース（本人の記録で停止中 / 他人の記録は数えない）で足りる
- 重なりの判定（半開区間・隣接）はドメイン層の `Overlaps` のテストが見る。ここでは「占有中の利用枠が渡った」ことが分かる 1 ケースで足りる

同一 tx で 2 つの集約を更新する usecase（取消の後に予約待ちを繰り上げるなど）では、両方の集約の `want{Table}` を見る。片方だけ見ると、もう片方が変わっていないことに気づけない。

### 6.3 ソース選択（query）

- Given: 選ばれるソースと選ばれないソースの両方に行を置く。両方に同じ値を置かない（どちらから来たか分からなくなる）
- When: ソースを決める入力の状態（進行中 / 終了）
- Then: `want` は選ばれたソースの行から作られる DTO。選ばれない側の値が混ざっていない
- ソースの数だけケースを書く。同じソースの中の WHERE の違いは永続化層

### 6.4 トランザクション境界

- commit: 成功ケースの `want{Table}` に、`Run` の中で書いた行が全部見える。`Execute` の後に `pool` で読むので、commit されていなければ見えない
- rollback: 途中の書き込みの後に失敗する前提を置く。mock で失敗を注入しない。DB 制約に当たる前提で起こす
  - 題材: `ApplyConfirmed` は current 行の UPDATE → 期限の DELETE → 基底イベントの INSERT → 確定イベントの INSERT の順に書く。前提に `reservation_base_events` の version 2 を先に置いておくと、3 手目の INSERT が `(reservation_id, version)` の一意制約に弾かれる。永続化層はこの制約違反を `rdb.ErrConflict` に翻訳する
  - Then: `wantErr: rdb.ErrConflict`。`wantReservations` は前提と同じ（version 1 の `tentative`）。1 手目の UPDATE が成功していたのに巻き戻ったことが、この 1 行で言える
- 書くのは rollback 1 ケース。失敗する手を変えて増やさない（どの手で失敗しても `Run` の振る舞いは同じ）

### 6.5 コマンド呼び分けと永続化

- 成功の配線: Given に復元できる行を置き、When で操作し、Then で current 行の状態と、対応するイベント表の行を見る。`reservation_confirmed_events` に 1 行あれば `ApplyConfirmed` が呼ばれたことが言え、`ApplyCancelled` ではなかったことも言える
- 拒まれて保存しない配線: 絞り込み（`AsTentative`）か操作（`Confirm`）が拒む前提を 1 つだけ置き、`wantErr` が sentinel で、行が変わらないことを見る。状態ごと（取消済み・期限切れ）に増やさない。それは `AsTentative` のテストの責務
- `(Result, bool)` の false: 拒まないが何も変えない操作（`Expire` / `RecordNoShow`）を呼ぶ usecase は、false のとき `Apply*` を呼ばず nil を返す。ケースは「期限前に期限到来を反映しても error にならず、行が変わらない」の 1 つ。true 側は成功の配線が兼ねる

```go
		res, ok := t.Expire(in.At)
		if !ok {
			return nil // 到来前。error にせず、既定の遷移にも丸めない
		}
		if err := u.repo.ApplyExpired(ctx, res.Event); err != nil {
			return fmt.Errorf("予約 %s の期限到来の反映: %w", in.ReservationID, err)
		}
		return nil
```

## 7. usecase のテストで見つかる欠陥

| 欠陥 | どのケースで見つかるか |
|---|---|
| VO の error を握りつぶして既定値で続けている | 入力解決のケースが `wantErr` ではなく成功して、行が変わる |
| 他の顧客の記録まで資格に数えている | 協調の「他人の記録は数えない」ケースが `ErrCustomerSuspended` で落ちる |
| `Run` の外で `Apply*` を呼んでいる（tx が無い） | 全ケースが `rdb.ErrNoTransaction` で落ちる |
| `Run` の中で error を返さず `Apply*` を続けている | rollback ケースの `wantReservations` が前提と一致しない |
| `AsTentative` の error を無視してゼロ値の `Tentative` で `Confirm` に進んでいる | 呼び分けの「確定済み」ケースで `wantErr` が `ErrAlreadyConfirmed` と一致しない |
| `Expire` の false で `Apply*` を呼んでいる | false の no-op ケースでイベント表に行が増える |
