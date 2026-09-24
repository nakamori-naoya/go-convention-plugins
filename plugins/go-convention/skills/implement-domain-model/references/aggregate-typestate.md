# 集約と typestate

**集約は、状態ごとに別の型を持ち、操作はその状態でできるものだけをメソッドに持ち、値レシーバが新しい状態の値とイベントを返す。** 資料の「状態と型の分割」がそのまま型の一覧であり、「できない操作」はメソッドが存在しないことで拒む。集約は VO と同じく不変の値で、操作はレシーバを変えない。

## 1. 和型と状態型

```go
// Reservation は予約の和型。封じた interface で、状態型は Tentative / Confirmed / Cancelled / Expired の 4 つ。
//
//sumtype:decl
type Reservation interface {
	ID() ID
	Customer() CustomerID
	Slot() TimeSlot
	Version() Version
	isReservation()
}

// core は全状態が持つ値（資料「持つもの」のうち状態によらないもの）。
type core struct {
	id       ID
	customer CustomerID
	slot     TimeSlot
	version  Version
}

// Tentative は仮押さえ予約。仮押さえ期限を持つ唯一の状態。
type Tentative struct {
	core
	deadline HoldDeadline
}

// Cancelled は取消済み予約。終端で、操作を一つも公開しない。
type Cancelled struct{ core }
```

| 規則 | 内容 | 理由 |
|---|---|---|
| 和型は封じた interface | 非公開のマーカーメソッド（`isReservation()`）と、全状態に共通の getter だけを持つ。コマンドを置かない。宣言に `//sumtype:decl` を付け、型スイッチの網羅を lint（`gochecksumtype`）に検査させる | 他 package の型が和型を満たせない。型スイッチが状態の数で閉じる。共通 interface に全コマンドを置いて拒む状態にスタブを書く形は採らない（資料「確定予約は確定を呼べない型にする」を破る） |
| 状態ごとに 1 つの struct | 資料「状態と型の分割」で「分ける」とある状態ごとに型。「分けない」なら 1 つの型で値の違いにする | 型がそのまま状態。できる操作がメソッドの有無で決まる |
| 状態によらない値は非公開 struct に集めて埋め込む | `core` が getter とマーカーを持ち、各状態型が埋め込む | 同じ getter を 4 回書かない。埋め込み先は非公開なので他 package から作れない |
| 状態だけが持つ値はその型のフィールド | `Tentative.deadline` / `Confirmed.noShowAt` | 資料「仮押さえ期限（仮押さえ予約のときだけ）」を型で守る。`*HoldDeadline` や「無効な期限」を全状態に持たせない |
| 終端状態は操作を持たない | `Cancelled` / `Expired` は getter だけ | 資料「元の状態へ戻らない」を、戻す経路が無いことで守る |
| 部分和型 | 資料が複数の状態をまとめて呼ぶ語（「現在有効な予約」）があれば、その語の interface を置く。`Active` は `Reservation` に共通のコマンド `Cancel` を足したもの | 呼ぶ側が「仮押さえか確定かを問わず取り消す」を型スイッチなしで書ける。資料に語が無い部分和型は作らない |
| 値レシーバ | 全メソッドが値レシーバ。ポインタレシーバを使わない | 集約は不変の値。操作は新しい値を返し、元の値は変わらない |
| 非ルートエンティティ | 型は公開、フィールドは非公開、生成と変更はルートの操作を通す。ルートと同じく不変で、ルートが新しい値を返すときに一緒に新しくなる | 不変条件はルートの操作で守る。題材には非ルートエンティティが無い |

## 2. 遷移結果型

```go
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
```

| 規則 | 内容 | 理由 |
|---|---|---|
| 遷移は `(Transition[Next, Event], error)` | 新しい状態の値とイベントを 1 つの struct で返し、返り値を 2 つに収める | 3 返り値を書かない。資料は操作ごとに発するイベントを 1 つ挙げており、型付きで返せば呼ぶ側とテストが型のまま扱える |
| 型エイリアスは操作ごと | `ConfirmResult` のように操作名 + `Result`。`Transition[...]` を呼ぶ側に書かせない | 操作のシグネチャが資料の操作名で読める |
| `Next` は状態型 | 和型（`Reservation`）ではなく `Confirmed` | 遷移先は資料で決まっている。呼ぶ側が絞り込み直さない |
| 状態を変えない操作も同じ形 | `RecordNoShow` は `Confirmed` → `Confirmed` | 版とイベントは進む。「状態は変わらない」は型が同じことで表す |
| 拒まないが何も変えない操作は `(Result, bool)` | 資料「拒む理由: なし（〜でなければ何も変えない）」の操作。`false` のとき `Result` はゼロ値 | 「起きなかった」はエラーではない。`error` を返すと呼ぶ側が正常系を `errors.Is` で選り分けることになる |
| 版は操作が進める | `v := t.version.Next()` を `Next` と `Event` の両方に入れる。生成は 1 | イベント型の永続化が楽観ロックと `base_events.version` に使う。イベントの版と `Next.Version()` は常に同じ |

## 3. 操作

```go
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
```

| 規則 | 内容 | 理由 |
|---|---|---|
| 操作は資料の操作と 1:1 | 資料「操作: 確定する」が `Confirm`。名前は資料の語を英語にした動詞 | 資料に無い公開コマンド（状態を変える公開メソッド）を作らない。`Set*` / `Update*` / `Bulk*` を作らない |
| 置き場は状態型のメソッドだけ | 「できる操作」の列にある状態型にだけメソッドを置く。同じ操作が複数の状態にあれば（`Cancel`）、非公開の共通関数を各状態型から呼ぶ | 状態違いは型で拒まれ、事前条件の検査は 1 か所に閉じる |
| 事前条件は資料の並びの順に確かめる | 資料の「事前条件」に書かれた順で `if` を並べ、最初に破れた理由の sentinel を返す | 複数の理由が同時に成り立つとき、どれを返すかが資料から決まる |
| 「〜である」の事前条件は型が保証する | 「仮押さえ予約であり」は `Tentative` のメソッドであること、「事前の取消が無い」は `Confirmed` であることで満たされ、`if` を書かない | 型で守れることを実行時に二重に確かめない |
| 事後条件は `Next` | 資料「確定予約になり、利用枠は変わらず」は `Confirmed{core: t.core.withVersion(v)}` で、変えないものは写す | 事後条件の検証はテストが `Next` の射影で行う |
| 呼び手の検査 | 「呼び手が予約者本人」は `by CustomerID` を引数に受けて比べる | 認可は境界の関心だが、資料が事前条件として書いた本人性は集約が守る |
| 公開する事前条件の検査メソッドを書かない | `CanConfirm()` / `Validate()` / `Ensure*()` を書かない | 呼ぶ側が先に検査して操作を呼ぶ形は、検査と操作の間に状態が変わる。操作が拒む |
| `log/slog` を import しない | ドメインの package はログを出さない。拒否はエラーで返す | 記録は最外境界の関心 |

## 4. 生成

```go
// Hold は操作「仮押さえ予約を成立させる」。
// 事前条件: 資格の顧客が予約者と同じで、予約可能であること。
// 「同じ会議室の重なる利用枠に有効な予約が無いこと」は集約の内側では確かめられないので、呼ぶ側と DB 制約が守る。
func Hold(id ID, customer CustomerID, slot TimeSlot, eligibility Eligibility, at time.Time) (HoldResult, error) {
```

- 生成は package 関数で、名前は資料の生成の操作（「仮押さえ予約を成立させる」→ `Hold`）。`New` を付けない（`New` は VO の生成）
- 返り値は最初の状態への遷移 `(HoldResult, error)`。版は 1
- 「生成の条件」のうち集約の内側で確かめられるものだけを検査する。他の集約や一覧を見ないと分からない条件（重なる有効な予約が無い）は資料「集約の境界」に従って外に置き、生成関数は検査しない。その sentinel（`ErrOverlappingSlot`）は生成を呼ぶ側と DB 制約の翻訳が返す
- 他の集約の状態は、判断に要る値（`Eligibility`）を引数で受ける。他の集約そのものや、その識別子から引く手段（リポジトリ）を受けない

## 5. 絞り込みと復元

```go
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
```

| 規則 | 内容 | 理由 |
|---|---|---|
| 絞り込みは状態ごとの package 関数 `AsX(r) (X, error)` | 和型から状態型（または部分和型 `AsActive`）へ。違う状態なら「今の状態」を表す sentinel | 永続化ポートは和型を返す。呼ぶ側の「復元 → 絞り込み → 操作」で、状態違いの拒否がここに集まる |
| 違う状態の sentinel は状態ごとに 1 つ | `ErrAlreadyConfirmed` / `ErrAlreadyCancelled` / `ErrAlreadyExpired`。どの操作を呼ぼうとしたかで変えない | 資料「確定済み予約の再確定」は `AsTentative` が `Confirmed` を受けたときに返る。「取消済み予約は元へ戻らない」は `ErrAlreadyCancelled` |
| 型スイッチは状態を全部列挙する | `case` を状態の数だけ書く。`default` に来るのは nil だけなので、`ErrNoReservation` を明示して返す。`panic` を書かず、既定の状態へ丸めない | 和型は封じてあり、列挙した以外の型は来ない。列挙が資料の状態の数と一致することが目で分かる |
| 復元は状態ごとの `RestoreX(...) X` | 保存済みの値（VO と `Version`）を受け取り、状態型を返す。`error` を返さない | 生成の条件は保存時に満たしている。VO の検査は行→ドメインの変換で `NewX` が済ませている |
| `Restore` は呼ぶ側が状態を知っているときだけ | 永続化からの復元とテストの Given に使う。usecase は `Restore` を呼ばない | 状態を知らずに復元するのは永続化の関心 |

## 6. 時刻と識別子

- `time.Now()` を呼ばない。成立時刻・確定時刻・判定時刻は操作の引数 `at time.Time` で受け、`UTC()` にしてから持つ
- 採番しない。`Hold` は `id ID` を引数で受ける。採番と時計は呼ぶ側（usecase）が持つ
- 資料の数（15 分・30 日・3 回・14 日）は package の非公開定数

## 7. 拒む — sentinel と返り値

| 規則 | 内容 |
|---|---|
| 拒む理由 1 行に sentinel 1 つ | 資料「拒むときの理由」の各行と、不変条件のうち操作が拒むもの（終端状態から戻らない）に `var ErrX = errors.New(...)` を 1 つ。資料に無く Go の都合で要るもの（VO の生成の条件、和型の nil）は同じ形で別の var ブロックに置き、資料に無いことをコメントに書く |
| 文言は日本語・句点なし・改行なし | 「何が拒まれたか」を書く（`"仮押さえ期限以降は確定できない"`）。「不正です」「エラー」のような何も言わない文言を書かない |
| 行末コメントに資料の語 | `// 仮押さえ期限以降の確定` のように、資料の「拒まれる操作」の語を置き、対応を目で追える |
| 判定は `errors.Is` | 呼ぶ側とテストは `errors.Is(err, reservation.ErrNotOwner)`。文言を比べない |
| ドメインは包まない | 集約と VO は sentinel をそのまま返す。文脈（どの予約か）は層境界で `fmt.Errorf("予約 %s の確定: %w", id.Value(), err)` のように `%w` で 1 回だけ足す。文脈は業務上の識別子で、VO ではなく `Value()` の primitive を渡す |
| `panic` を書かない | 「来ないはず」の分岐（和型の nil）も明示の sentinel で返す。既定値へ丸めない |
| 返り値は最大 2 つ | `(T, error)` か `(T, bool)`。`(Next, Event, error)` を書かず、遷移結果型に収める |
| `errors.Join` / `errors.AsType` をドメインで使わない | 複数の理由を同時に返さない（最初に破れた理由を 1 つ返す）。外部の型の翻訳はドメインの外 |

## 8. 永続化ポート

集約と同じ package に、集約ごとに 1 つの interface を置く。

```go
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

データモデルがイベント系テーブルを持たない集約は通常型で、集約の値を保存する。集約は版を持たない。題材に無い別の集約（予約待ち。package `waitlist`）を仮定した形:

```go
// WaitlistRepository は予約待ちの永続化ポート（通常型）。Create と Update を分け、集約の値を受け取る。
type WaitlistRepository interface {
	FindByID(ctx context.Context, id waitlist.ID) (waitlist.Waitlist, error)
	Create(ctx context.Context, w waitlist.Waiting) error
	Update(ctx context.Context, w waitlist.Waitlist) error
}
```

| 規則 | 内容 | 理由 |
|---|---|---|
| ドメインが定義する | 「interface は使う側で定義する」の例外。永続化ポートと和型は集約の package が定義し、usecase は自前の interface を切らない | 契約が集約ごとに 1 か所になる。偽物を作らない前提では使う側定義の利点が無い |
| `FindByID` は和型を返す | `FindTentativeByID` のような状態指定の取得を置かない | 状態違いの拒否は `AsX` が担う |
| イベント型は `Apply{Event}(ctx, evt)` | 集約を受け取らない。イベントごとに 1 メソッド。集約もイベントも版を持つ | 保存するのは起きたこと。楽観ロックは版で行う |
| 通常型は `Create` / `Update` | 集約の値を受け取る。版を持たない | 状態の上書きで足りる |
| `Delete` を置かない | 資料に「消す」操作が無い限り置かない | 終端状態は値として残る |
| 一覧・件数・検索を置かない | 読み取りの関心は別のポートへ | 永続化ポートは集約の復元と保存だけ |
| tx を受け取らない | `ctx` から取る。引数に `pgx.Tx` を置かない | tx を張るのは usecase。ドメインは永続化の package を import しない |
