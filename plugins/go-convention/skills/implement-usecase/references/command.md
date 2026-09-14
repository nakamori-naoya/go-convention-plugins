# command の形

**command は 1 つの業務イベントを起こす。入力を解決し、tx を張り、集約を復元または生成し、状態を絞り込み、操作を呼び、結果を保存する。それ以外をしない。** 判断はすべて集約と VO が持ち、usecase は材料を集めて渡す。

## 1. 1 型 1 `Execute`

```go
package usecase

import (
	"time"

	"example.com/roomflow/reservation"
	"example.com/roomflow/tx"
)

// ConfirmReservation は業務イベント「予約が確定した」を起こす command。
type ConfirmReservation struct {
	tx   *tx.Manager
	repo reservation.Repository
}

func NewConfirmReservation(txm *tx.Manager, repo reservation.Repository) *ConfirmReservation {
	return &ConfirmReservation{tx: txm, repo: repo}
}

// ConfirmReservationInput は境界が受け取った値。primitive だけを持つ。
type ConfirmReservationInput struct {
	ReservationID string    // 予約番号
	CustomerID    string    // 確定を求めた予約者
	At            time.Time // 確定の時刻。受け取った境界（RPC の入口）がサーバーの時計で 1 回だけ決める
}
```

| 項目 | 規則 | 理由 |
|---|---|---|
| 単位 | domain-rule 資料の「業務イベント」1 つに型 1 つ。`ConfirmReservation` / `HoldReservation` / `CancelReservation` / `ExpireReservation` | 業務イベントが tx の単位で、テストの単位で、名前の単位になる |
| 名前 | 資料の業務語（動詞 + 集約）。`Usecase` 接尾辞を付けない。ファイルは `usecase/{operation}_{aggregate}.go` に 1 つ | 資料と RPC と usecase の語彙が揃い、`Create` / `Update` の機械語で業務が消えない |
| 公開メソッド | `Execute(ctx context.Context, in Input) error`。返すものがあれば `(Output, error)` | 入口が 1 つなら、呼ぶ側（RPC の入口・worker）が usecase の中を知らずに済む |
| Input / Output | `{Type}Input` / `{Type}Output`。フィールドは primitive（`string` / `time.Time` / `int` / `bool`）。VO・集約・proto を持たない | 境界が受け取った値をそのまま運び、解決（VO の `New*`）を usecase が行う。入力不正の sentinel が usecase から出て、境界の対応表が 1 か所で翻訳できる |
| 依存 | `*tx.Manager`、ドメインの `Repository`、読み取りポート、`IDGenerator`。全部をコンストラクタの引数で受け、`*T` を返す。時計は持たない | 組み立ては 1 か所（入口の規約が決める）。任意の依存（あれば使う）を持たない |
| 非公開関数 | 置かない。長くなったら分割ではなく、資料に無い判断が混ざっていないかを疑う | `diff*` / `plan*` / `sync*` は業務の差分計算で、置き場は集約 |

## 2. 手順は 6 段

```
入力の解決 → tx を張る → 復元 または 生成 → 絞り込み → 操作 → 保存
（Run の外）   （Run）     （FindByID / Hold）   （AsTentative） （Confirm） （ApplyConfirmed / Update）
```

| 段 | 何をするか | 置き場 | 出るエラー |
|---|---|---|---|
| 入力の解決 | `string` → `reservation.NewID` / `NewCustomerID` / `NewRoomCode` / `NewTimeSlot` | `Run` の前 | VO の生成の条件の sentinel（`ErrIDRequired` / `ErrTimeSlotNotOrdered`）。境界では InvalidArgument |
| tx を張る | `u.tx.Run(ctx, func(ctx context.Context) error { ... })` | — | `Run` 自身の失敗（開始・commit） |
| 復元 | `u.repo.FindByID(ctx, id)`。和型が返る | `Run` の中 | `rdb.ErrNotFound` |
| 生成 | `reservation.Hold(id, customer, slot, eligibility, in.At)`。復元の代わり | `Run` の中 | 生成の条件の sentinel（`ErrCustomerSuspended`） |
| 絞り込み | `reservation.AsTentative(r)` / `AsActive(r)`。操作を持つ状態型へ | `Run` の中 | 状態違いの sentinel（`ErrAlreadyConfirmed`） |
| 操作 | `t.Confirm(in.At, by)`。`(Result, error)` か `(Result, bool)` | `Run` の中 | 事前条件の sentinel（`ErrHoldDeadlinePassed` / `ErrNotOwner`） |
| 保存 | イベント型は `u.repo.ApplyConfirmed(ctx, res.Event)`、通常型は `u.repo.Update(ctx, res.Next)` | `Run` の中 | DB 制約の翻訳（`ErrOverlappingSlot`）、`rdb.ErrConflict` |

- 絞り込みは「操作を呼ぶために型を選ぶ」ことで、「状態を見て判断する」ことではない。`switch r := r.(type)` や `if _, ok := r.(reservation.Confirmed); ok` を usecase に書かない。違う状態の拒否は `As*` が sentinel で返す
- 生成のときは復元が無く、復元のときは生成が無い。両方があるのは複数集約の協調で、その形は [cross-aggregate.md](cross-aggregate.md)
- 通常型の保存は `res.Next`（次の状態の値）、イベント型の保存は `res.Event`（起きたこと）。同じ `Transition` から取り違えない

### `ConfirmReservation`（復元 → 絞り込み → 操作 → 保存）

§1 の続き。import に `context` と `fmt` を足す。

```go
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
```

資料 BDD-023「確定済み予約の再確定」は `AsTentative` が `ErrAlreadyConfirmed` を返して止まる。BDD-015「期限と同時刻の確定」は `Confirm` が `ErrHoldDeadlinePassed` を返す。usecase はどちらも知らず、文脈を足して返すだけである。

## 3. ID は usecase が用意し、時刻は Input で受ける

ドメインは `time.Now()` も採番もしない。時刻と識別子は操作の引数で受ける。識別子を用意するのは usecase（`IDGenerator`）、時刻を決めるのは usecase を呼ぶ境界（RPC の入口ならサーバーの時計、worker なら判定時刻）で、usecase は Input の `At` をそのまま集約へ渡す。**usecase は `Clock` を持たない。**

```go
// IDGenerator は予約番号の採番。usecase が要る分だけ定義し、実装（標準の uuid を使うもの）は組み立てで注入する。
type IDGenerator interface {
	NewReservationID() (reservation.ID, error)
}
```

| 操作 | 時刻の持ち主 | ID の持ち主 | 理由 |
|---|---|---|---|
| 生成（`Hold`） | Input の `At`（RPC の入口がサーバーの時計で 1 回決める） | usecase が `IDGenerator.NewReservationID()` を 1 回 | 成立時刻は期限（15 分後）の起点。時計を usecase に持たせると `Execute` の結果が呼ぶたびに変わり、決定的に検証できない。採番は「この usecase が生んだ新しい事実」で、DB にも RPC にも無いので usecase が持つ |
| 遷移（`Confirm` / `Cancel`） | Input の `At`（RPC の入口がサーバーの時計で 1 回決める） | 無し（復元した集約が持つ） | 期限の判定に使う時刻を要求の本文（クライアント申告）から受けない。サーバーの時計が 1 回決め、usecase はそれを渡す |
| 拒まない操作（`Expire` / `RecordNoShow`） | Input の `At`（worker が判定時刻を 1 回決める） | 無し | worker が「この時刻で判定する」と決めて渡す。掃く対象が 100 件なら同じ時刻で 100 回呼ぶ |

- 時刻の持ち主は Input の `At` の 1 つ。usecase に `Clock` を持たせない。`time.Now()` を usecase に書かない
- 同じ `Execute` の中で時刻は `in.At` の 1 つだけを使う（材料の導出と生成に別の時刻を使わない）
- `IDGenerator` の実装（標準の `uuid`）は組み立ての側にあり、usecase は interface だけを知る。採番は `Run` の前に 1 回

### `HoldReservation`（材料の読み取り → 生成 → 保存）

生成は復元が無く、集約の外で守る不変条件と、他の要素から導く材料が要る。材料は読み取りポート（[query.md](query.md) §2）で読み、判定はドメインの関数を呼ぶ。「同じ会議室の重なる利用枠に有効な予約が無い」の守り方は [cross-aggregate.md](cross-aggregate.md) §4。

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

// ActiveReservationReader は「同じ会議室の重なる利用枠に有効な予約が無い」を確かめる材料を読む読み取りポート。
type ActiveReservationReader interface {
	// ListActiveOverlapping は会議室の、[startsAt, endsAt) と重なる現在有効な予約の利用枠を返す。
	// 重なりは半開区間で、日単位ではない（SQL の条件は ends_at > startsAt AND starts_at < endsAt）。
	ListActiveOverlapping(ctx context.Context, roomCode string, startsAt, endsAt time.Time) ([]query.ActiveSlot, error)
}

// NoShowReader は顧客の予約資格を導く材料（その顧客の予約で起きた無断不利用の時刻）を読む読み取りポート。
// 直近 30 日への絞り込みは資料の数で、ドメインの NewEligibility が行う。
type NoShowReader interface {
	ListNoShowAt(ctx context.Context, customerCode string) ([]time.Time, error)
}

// HoldReservation は業務イベント「仮押さえ予約が成立した」を起こす command。時計は持たない。
type HoldReservation struct {
	tx      *tx.Manager
	repo    reservation.Repository
	active  ActiveReservationReader
	noShows NoShowReader
	ids     IDGenerator
}

func NewHoldReservation(txm *tx.Manager, repo reservation.Repository, active ActiveReservationReader, noShows NoShowReader, ids IDGenerator) *HoldReservation {
	return &HoldReservation{tx: txm, repo: repo, active: active, noShows: noShows, ids: ids}
}

type HoldReservationInput struct {
	CustomerID string    // 予約者
	RoomCode   string    // 会議室
	StartsAt   time.Time // 利用開始
	EndsAt     time.Time // 利用終了
	At         time.Time // 成立の時刻。RPC の入口がサーバーの時計で 1 回だけ決める。期限（15 分後）と資格の判定の起点
}

type HoldReservationOutput struct {
	ReservationID string    // 採番した予約番号
	ExpiresAt     time.Time // 仮押さえ期限
}

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
		// 集約の外で守る不変条件。材料を読み（同じ tx）、判定はドメイン（Overlaps）、返すのは資料の sentinel。
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
		// 他の要素から導く材料。導出（30 日で 3 回、14 日間）はドメインの NewEligibility が行う。
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

- `for` の中で呼ぶのは `Overlaps` だけである。`a.StartsAt.Before(in.EndsAt)` のように usecase で時刻を比べた瞬間、半開区間の定義が 2 か所になる。読み取りポートが SQL で重なる行だけを返していても、判定はドメインで確かめ直す（SQL の条件は絞り込みで、規則の置き場ではない）
- `len(noShowAt) >= 3` を usecase に書かない。数は資料のもので、`NewEligibility` が持つ。usecase は材料を集めて渡すだけ
- `Run` の中の読み取りポートは、復元・保存と同じ tx に乗る（読み取りポートの実装は ctx の tx があればそれで読む）
- 同じ会議室への同時の仮押さえ（資料 BDD-004）は、この読み取り検査では守れない。`ApplyHeld` の排他制約違反をリポジトリが `ErrOverlappingSlot` に翻訳して一方だけを通す。読み取り検査は「先に分かる拒否を先に返す」ためで、保証ではない
- Output は `Run` の外の変数に書き、error のときはゼロ値を返す

## 4. 拒まない操作 `(Result, bool)`

「拒む理由: なし（〜でなければ何も変えない）」の操作は `(Result, bool)` を返す。false は「何も起きなかった」であり、失敗ではない。usecase は false で nil を返し、`Run` は書き込み無しで commit する。

### `ExpireReservation`（false は何もしない）

package と import は §3 と同じ。1 件 1 tx で、期限を掃く worker（`DueHoldReader.ListDueHoldIDs(ctx, at)` で対象の予約番号を読み、1 件ごとに `Execute` を呼ぶ）が持ち主。usecase の中で対象を一覧して `for` で回す形（1 tx に束ねる形）にしない。データモデル資料 BDD-002（期限と同時刻の確定要求で期限切れを記録する）の「期限切れの記録」は、確定の command が担うのではなく、worker がこの `ExpireReservation` で担う。確定の command は `Confirm` の `ErrHoldDeadlinePassed` を返すだけである。

```go
// ExpireReservation は業務イベント「仮押さえ期限が到来した」を反映する command。期限を掃く worker が 1 件ずつ呼ぶ（1 件 1 tx）。
type ExpireReservation struct {
	tx   *tx.Manager
	repo reservation.Repository
}

func NewExpireReservation(txm *tx.Manager, repo reservation.Repository) *ExpireReservation {
	return &ExpireReservation{tx: txm, repo: repo}
}

type ExpireReservationInput struct {
	ReservationID string    // 予約番号
	At            time.Time // 期限到来を判定する時刻。worker が 1 回決める
}

func (u *ExpireReservation) Execute(ctx context.Context, in ExpireReservationInput) error {
	id, err := reservation.NewID(in.ReservationID)
	if err != nil {
		return fmt.Errorf("期限到来の反映の入力: %w", err)
	}
	return u.tx.Run(ctx, func(ctx context.Context) error {
		r, err := u.repo.FindByID(ctx, id)
		if err != nil {
			return fmt.Errorf("予約 %s の期限到来の反映: %w", in.ReservationID, err)
		}
		t, err := reservation.AsTentative(r)
		if err != nil {
			return fmt.Errorf("予約 %s の期限到来の反映: %w", in.ReservationID, err)
		}
		res, ok := t.Expire(in.At)
		if !ok {
			return nil // 到来していない。何も起きなかったので正常終了
		}
		if err := u.repo.ApplyExpired(ctx, res.Event); err != nil {
			return fmt.Errorf("予約 %s の期限到来の反映: %w", in.ReservationID, err)
		}
		return nil
	})
}
```

| する | しない | 理由 |
|---|---|---|
| `if !ok { return nil }` | `if !ok { return ErrNotExpired }` | 何も起きなかったことを拒否として境界に記録させない |
| `AsTentative` の sentinel（`ErrAlreadyConfirmed`）はそのまま返す | `errors.Is(err, reservation.ErrAlreadyConfirmed)` で nil に読み替える | 期限到来の直前に確定されたなら、それは worker の境界が Info で記録する業務上の拒否で、無かったことではない。読み替えは丸めである |
| 掃く対象の選定（期限が過ぎた仮押さえ予約の一覧）は worker の読み取りポート（`DueHoldReader.ListDueHoldIDs(ctx, at)`）で行い、worker が 1 件ごとに `Execute` を呼ぶ | `FindByID` を全予約に対して呼ぶ、状態指定取得をリポジトリに足す、usecase の中で一覧して `for` で回す | 一覧は読み取りモデルの関心。1 件の失敗が他の件を巻き込まない（[transaction.md](transaction.md) §2） |

## 5. 通常型の保存

イベント型（題材の予約）は `Apply{Event}(ctx, res.Event)`。通常型（イベント系テーブルを持たない集約。題材に無い予約待ちを `waitlist` として仮定）は `Create(ctx, res.Next)` / `Update(ctx, res.Next)` で次の状態の値を保存する。

```go
// 通常型: 生成なら Create、遷移なら Update。渡すのは res.Next（次の状態）
// Promote は拒まない操作 (PromoteResult, bool)。false は「予約待ち中でなければ何も変えない」
res, ok := waiting.Promote(in.At)
if !ok {
	return nil
}
if err := u.waitlists.Update(ctx, res.Next); err != nil {
	return fmt.Errorf("予約待ち %s の繰上げ: %w", in.WaitlistID, err)
}
```

| 型 | 生成 | 遷移 | 渡すもの |
|---|---|---|---|
| イベント型 | `ApplyHeld(ctx, res.Event)` | `ApplyConfirmed(ctx, res.Event)` | `Transition.Event` |
| 通常型 | `Create(ctx, res.Next)` | `Update(ctx, res.Next)` | `Transition.Next` |

どちらの型かはドメインの `Repository` interface が決めている。usecase は interface にあるメソッドを呼ぶだけで、型を選ばない。

## 6. エラー

**package を出る `return` ごとに `fmt.Errorf("<操作> <業務 ID>: %w", err)` で文脈を 1 回足す。分類しない。ログしない。丸めない。フォールバックしない。ガード節で早期リターン。** 詳しい規則はエラーの規約にある。usecase で守ることは次の 6 つ。

| 規則 | する | しない |
|---|---|---|
| 文脈は 1 回 | `fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)` | `return err`（素通し。どのコマンドの途中かが消える）、二重に包む |
| 文脈の中身 | 操作の業務語と業務 ID（primitive。`id.Value()` か Input の文字列） | 関数名、VO をそのまま `%v`、氏名やメール |
| 分類しない | 受け取った error に文脈を足して返す | `errors.Is` で全部を分類してから返す、`connect.NewError`、`Kind` / `Code` を付ける |
| ログしない | 返す。最外境界が返った error と ctx から 1 回記録する | 返す直前の `slog.Error`、`log/slog` の import |
| 丸めない | 入力不正・`ErrNotFound`・読み取り失敗は返す | 既定値へ倒す（`id = defaultID`）、`ErrNotFound` を「新規」に読み替える、`(T, bool)` の false 以外を nil にする |
| フォールバックしない | 主経路の error を返す。別経路が業務上必要なら、それは入力と時刻で決めるソース選択（[query.md](query.md) §4） | `if err != nil { r, err = u.other.FindByID(...) }`、`for` で再試行 |

判定（`errors.Is`）を書くのは、資料の操作が「無ければ〜する」のように sentinel で次の手を決めるときだけで、その分岐は資料の語でコメントする。フォールバックがどうしても要ると判断したら、書く前に利用者の許可を得る。
