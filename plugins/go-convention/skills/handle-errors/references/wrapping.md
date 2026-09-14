# 包み方・判定・返す形

**error は package を出る `return` で 1 回だけ `fmt.Errorf("<操作> <業務 ID>: %w", err)` で包み、同じ package 内は `return err` で素通しする。判定は `errors.Is`。** 包むのは「その error に文脈を足せる層」だけで、自分が起こしていない error を通すだけの関数は包まない。

## 1. 境界で 1 回

| 場所 | する | 理由 |
|---|---|---|
| ドメイン package の中 | sentinel をそのまま `return`。包まない | 文脈（どのコマンドの途中か）はドメインが知らない。呼ぶ側が足す。テストは sentinel を `require.ErrorIs` で受け取る |
| リポジトリが外へ返すとき | `fmt.Errorf("予約 %s の取得: %w", id.Value(), err)` を 1 回 | どの操作でどの予約に起きたかを足す。外部エラー（pgx）の文言はそのまま連鎖に残る |
| usecase が外へ返すとき | `fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)` を 1 回 | どのコマンドの途中で止まったかを足す。分類（Code の判断）はしない |
| `tx.Manager.Run` が `fn` の error を返すとき | 包まない。`fn` の error に rollback の失敗を `errors.Join` して返す（§5）。自分が起こした error（開始・commit の失敗）だけ包む | `fn` の error に `tx` が足せる文脈は無い。rollback の失敗は `fn` の失敗と独立した別の失敗なので、捨てずに並べる。`errors.Is` は `Join` の中も探すので、呼ぶ側の判定は変わらない |
| handler 本体 | `return nil, err` で素通し | 翻訳は interceptor が 1 か所で行う |
| interceptor が `next` の error を受けたとき | 包まず `connect.Error` へ翻訳（[translation.md](translation.md) §5） | ここが最外境界。以後は連鎖を読む層が無い |

`usecase.ConfirmReservation.Execute`（package を出る `return` ごとに 1 回。同じ文脈でも経路ごとに書く）:

```go
package usecase

import (
	"context"
	"fmt"
	"time"

	"example.com/roomflow/reservation"
	"example.com/roomflow/tx"
)

type ConfirmReservation struct {
	tx   *tx.Manager
	repo reservation.Repository
}

type ConfirmReservationInput struct {
	ReservationID string
	CustomerID    string
	At            time.Time
}

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

連鎖は外から内へ読める: `予約 R-0101 の確定: 予約 R-0101 の取得: 対象が見つからない`。同じ ID が 2 回現れてよい。各層が自分の操作と自分の知る ID を足すだけで、下の層が何を足したかを上の層が見ない。

ドメイン側は包まない（`reservation.AsTentative`。和型は封じてあるので `default` に来るのは nil だけで、そこにも panic ではなく sentinel を置く。`r.ID()` のように nil のメソッドを呼ぶ文脈を足さない）:

```go
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

// Confirm の事前条件は資料の順に確かめる: 期限が到来していない → 呼び手が予約者本人。
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

## 2. `fmt.Errorf` の書き方

| 規則 | する | しない | 理由 |
|---|---|---|---|
| 動詞 | `%w` | `%v` / `%s` / `err.Error()` / `errors.New(err.Error())` | `%v` は連鎖を切り、`errors.Is` が下の sentinel に届かなくなる |
| `%w` の数 | 1 つ | `fmt.Errorf("%w: %w", ErrA, err)` | 2 つ包むと「どの sentinel か」が 1 つに決まらず、翻訳表が最初に一致したものを拾う。値が要るなら型付きエラー（[sentinels.md](sentinels.md) §6） |
| 文脈の形 | `<操作> <業務 ID>: %w`（`予約 %s の確定: %w`） | `failed to confirm: %w` / `ConfirmReservation: %w` / `error: %w` | 日本語で「何をしようとしたか」。関数名は文脈ではない |
| 文脈に入れる値 | 業務 ID（予約番号・顧客番号・会議室コード）、件数、状態名 | 氏名・メール・電話・住所・外部サービスの利用者 ID・トークン・リクエスト本文 | 連鎖はそのままログに出る |
| 文脈に入れる VO | `id.Value()` のような primitive | VO をそのまま `%v` / `%s` に渡す | VO に `String()` は無い。`%v` は非公開フィールドをそのまま印字する |
| 区切り | `: `（半角コロン＋空白） | `：` / ` - ` / `(...)` | Go 標準の連鎖の形。ログの 1 行を `: ` で割ればどの層で何が起きたかが読める |

## 3. 判定は `errors.Is`

```go
r, err := u.repo.FindByID(ctx, id)
if errors.Is(err, rdb.ErrNotFound) {
	// 「無ければ作る」のように、呼ぶ側が sentinel で次の手を決めるときだけ判定する
}
```

| する | しない | 理由 |
|---|---|---|
| `errors.Is(err, reservation.ErrNotOwner)` | `err == reservation.ErrNotOwner` | 包まれた error に `==` は届かない |
| `errors.Is` | `err.Error() == "..."` / `strings.Contains(err.Error(), "見つからない")` | 文言は変わる。sentinel は変わらない |
| `errors.Is` | 自前のエラーの型 switch（`switch err.(type)`） | 自前の型は例外的にしか作らない。作ったときも `Is` で sentinel に答える |
| 判定が要る場所だけ判定する | 受け取った error をすべて分類してから返す | usecase は文脈を足すだけ。分類は境界の対応表の仕事 |

## 4. `errors.AsType[T]` は境界の翻訳だけ

`errors.AsType[T]`（Go 1.26 以降）は、連鎖の中から型 `T` の error を取り出す。使う場所は外部ライブラリの型付きエラーを読む境界に限る。

| 場所 | 型 | 何のため |
|---|---|---|
| リポジトリ | `*pgconn.PgError` | `Code`（SQLSTATE）と `ConstraintName` を読み、DB 制約違反をドメイン sentinel へ写す（[translation.md](translation.md) §3） |
| interceptor | `*connect.Error` | 認可の interceptor などが既に翻訳済みの error をそのまま通す（[translation.md](translation.md) §5） |
| 型付きエラーを作った操作の呼び手 | その型 | 呼び手が次の判断に使う値を読む。1 か所 |

```go
pgErr, ok := errors.AsType[*pgconn.PgError](err)
if !ok {
	return err
}
```

usecase・ドメイン・handler 本体に `errors.AsType` が現れたら、外部の型がそこまで漏れている。翻訳をリポジトリか interceptor へ戻す。`errors.As(err, &target)` は `AsType` に置き換える（型を 2 回書かず、ポインタの取り違えが無い）。

## 5. `errors.Join` はドメイン外の独立した複数失敗だけ

ドメインの拒否は 1 操作に 1 つで、最初に成り立たなかった事前条件の sentinel を返して止まる（`Confirm` は `ErrHoldDeadlinePassed` を返したら本人かを見ない）。複数の失敗を束ねるのは、**互いに独立していて、呼ぶ側が全部を一度に知りたい**ときに限る。

| 使う | 使わない | 理由 |
|---|---|---|
| 入力 DTO の複数フィールドを一度に検証し、全部の不備を返す | ドメインの事前条件を複数束ねる | 事前条件には順序がある（期限が過ぎていれば本人かを見る意味が無い） |
| `defer` の `Close` の error を本体の error と合成する | `Join` で「原因」と「文脈」を 2 つ並べる | 文脈は `%w` で足す。`Join` は並列の失敗を並べるもの |
| `tx.Manager.Run` が `fn` の error に rollback の失敗を合成する | `_ = t.Rollback(ctx)` で rollback の失敗を捨てる | rollback が失敗した事実は `fn` の失敗と独立で、境界が記録すべき情報。捨てると接続の異常が見えない |

```go
func writeReport(path string, body []byte) (err error) {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("報告書 %s の作成: %w", path, err)
	}
	defer func() {
		err = errors.Join(err, f.Close())
	}()
	if _, err := f.Write(body); err != nil {
		return fmt.Errorf("報告書 %s の書き込み: %w", path, err)
	}
	return nil
}
```

`tx.Manager.Run`（名前付き結果を `defer` で書き換える。`return` には値を書く）:

```go
func (m *Manager) Run(ctx context.Context, fn func(ctx context.Context) error) (err error) {
	t, err := m.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("トランザクションの開始: %w", err)
	}
	defer func() {
		if err == nil {
			return
		}
		// commit を試みた後の Rollback は ErrTxClosed を返す。それは失敗ではないので束ねない
		if rbErr := t.Rollback(ctx); rbErr != nil && !errors.Is(rbErr, pgx.ErrTxClosed) {
			err = errors.Join(err, rbErr)
		}
	}()
	if err := fn(context.WithValue(ctx, ctxKey{}, t)); err != nil {
		return err // 包まない。fn の error に足せる文脈は無い
	}
	if err := t.Commit(ctx); err != nil {
		return fmt.Errorf("トランザクションのコミット: %w", err)
	}
	return nil
}
```

`errors.Is` は `Join` の中も探すので、束ねた後も sentinel の判定は壊れない。`fn` が `ErrHoldDeadlinePassed` を返し rollback も失敗した error は、境界の対応表で `FailedPrecondition` に写り、ログには両方の失敗が残る。

## 6. 返す形は 2 つだけ

| 状況 | 形 | 例 |
|---|---|---|
| 拒む理由がある操作、外部要因で失敗しうる操作 | `(T, error)` | `Confirm(at, by) (ConfirmResult, error)` / `FindByID(ctx, id) (Reservation, error)` |
| 拒まないが何も変えない操作、無いことが失敗ではない問い合わせ | `(T, bool)` | `Expire(at) (ExpireResult, bool)` / `NoShowAt() (time.Time, bool)` / `tx.From(ctx) (pgx.Tx, bool)` |

| しない | 代わりに | 理由 |
|---|---|---|
| `(T, bool, error)` | 「無い」が失敗なら `(T, error)` で sentinel、失敗でないなら `(T, bool)` | 3 つ目の返り値は「無いのか失敗なのか」を呼ぶ側に毎回判断させる |
| `(Next, Event, error)` のように値を 2 つ返す | 結果 struct（`Transition[Next, Event]` を `ConfirmResult` の別名で） | 返り値は最大 2 つ。値が複数要るなら名前を付けた struct が読める |
| error と一緒に意味のある値を返す（`return partial, err`） | error のとき `T` はゼロ値 | 呼ぶ側が error を見ずに値を使う事故を作らない。テストは error 時に `assert.Zero(t, got)` を見る |
| `error` だけを返して結果を引数のポインタに書く | `(T, error)` | 出力引数は「error のとき何が書かれているか」が読めない |

## 7. panic を書かない

| 書かない | 代わりに | 理由 |
|---|---|---|
| 業務の拒否・不正な入力・想定外の状態で `panic` | sentinel か `fmt.Errorf` で error を返す（§1 の `AsTentative` の `default` も `ErrNoReservation`） | 1 リクエストの失敗でプロセスを落とさない。error なら境界が翻訳して記録できる |
| 本番経路で `MustNewID(...)` / `MustParse(...)` | `NewID(...)` の error を返す | `Must*` を書いてよいのはテストと、package 変数の定数（`regexp.MustCompile`）だけ |
| usecase・リポジトリ・ドメインで `recover` | 何も書かない | `recover` は最外境界（interceptor・worker の supervisor）が 1 か所で行い、スタックを記録して `Internal` を返す |
| `log.Fatal` / `os.Exit` を `main` 以外で | error を `main` の `run(ctx) error` まで返す | 終了の判断は 1 か所 |

## 8. 捨てない

| 書かない | 書く |
|---|---|
| `v, _ := reservation.NewID(s)` | `v, err := reservation.NewID(s); if err != nil { return ..., err }` |
| `if err != nil { log(...) }` で続行 | 返す。記録は境界が行う（ログの規約） |
| `defer f.Close()` で書き込みの Close を捨てる | §5 の `errors.Join` で本体の error に合成する |
| `defer func() { _ = res.Body.Close() }()` 以外の `_ =` | 読み取り専用の Close だけが唯一の例外 |

## 9. 丸めない・フォールバックしない・早期リターン

**error を既定値に置き換えて続行しない。別経路で黙って再試行して続けない。エラー分岐はガード節の早期リターンで書き、正常系を `else` に入れない。** 丸めとフォールバックは失敗を隠し、原因の行から遠い場所で別の症状として現れる。error は起きた場所で返せば、境界が翻訳して記録し、原因の行が連鎖に残る。

### 既定値に丸めない

```go
// しない: 取得できなければ空で続ける。予約が無いのか読めなかったのかが消え、後段が「重なる予約なし」と判断して二重予約を作る
active, err := u.active.ListActiveOverlapping(ctx, in.RoomCode, in.StartsAt, in.EndsAt)
if err != nil {
	active = nil
}

// する: 返す。境界が Internal として記録し、原因の行が連鎖に残る
active, err := u.active.ListActiveOverlapping(ctx, in.RoomCode, in.StartsAt, in.EndsAt)
if err != nil {
	return fmt.Errorf("会議室 %s の有効な予約の取得: %w", in.RoomCode, err)
}
```

```go
// しない: 不正な値を初期値へ倒す。空の予約番号が「予約番号 0000」として先へ進む
id, err := reservation.NewID(in.ReservationID)
if err != nil {
	id = defaultID
}

// する: 生成の条件を満たさない入力は sentinel で返す
id, err := reservation.NewID(in.ReservationID)
if err != nil {
	return fmt.Errorf("予約の確定の入力: %w", err)
}
```

`(T, bool)` の `false` も同じである。`Expire` が `false` を返したら「何も起きなかった」として先へ進むのは規約どおりだが、`FindByID` の `ErrNotFound` を「無いなら新規扱い」に読み替えるのは丸めである。無いことが業務上「新規」を意味する操作なら、それは資料の操作であり、`errors.Is(err, rdb.ErrNotFound)` で明示的に分岐して資料の語で書く（§3）。

### フォールバックしない

```go
// しない: 主経路が失敗したら別経路で黙って続ける。どちらの結果を返したかが呼ぶ側にもログにも残らない
r, err := u.repo.FindByID(ctx, id)
if err != nil {
	r, err = u.cache.FindByID(ctx, id)
}

// する: 主経路の error を返す。別経路が業務上必要なら、それは「ソース選択」という usecase の明示的な手順であり、条件は error ではなく入力や状態で決める
r, err := u.repo.FindByID(ctx, id)
if err != nil {
	return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
}
```

再試行（同じ経路をもう一度）も同じである。再試行が要る操作は、回数・間隔・対象の error を明示した専用の手順として書き、規約上の途中ログの対象になる（ログの規約）。「失敗したらもう一度」を `for` で囲って黙らせない。

**どうしてもフォールバックが要ると判断したら、書く前に利用者の許可を得る。** 何を丸めたいか、なぜ error で返せないか、丸めた結果を誰がどう知るかを示して問う。許可を得て書いたフォールバックは、その箇所と許可の内容を報告に載せる。

### ガード節で書く

```go
// しない: 正常系が else に沈み、エラー分岐が増えるたびに字下げが深くなる
r, err := u.repo.FindByID(ctx, id)
if err == nil {
	t, err := reservation.AsTentative(r)
	if err == nil {
		res, err := t.Confirm(in.At, by)
		if err == nil {
			return u.repo.ApplyConfirmed(ctx, res.Event)
		}
		return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
	}
	return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
}
return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)

// する: err != nil はその場で return。正常系は字下げ 0 で上から下へ読める（§1 の Execute）
r, err := u.repo.FindByID(ctx, id)
if err != nil {
	return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
}
t, err := reservation.AsTentative(r)
if err != nil {
	return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
}
```

| 規則 | 理由 |
|---|---|
| `if err != nil { return ... }` の中身は `return` で終わる | 分岐の中で続行すると丸めかフォールバックになる |
| `if err == nil { 正常系 }` と書かない | 正常系が字下げされ、後から足すエラー分岐が末尾に溜まる |
| `if x, err := f(); err != nil { return ... }` の後に `x` を使うなら、`x, err := f()` と分けて書く | `if` の初期化文で宣言した変数は `if` の外で見えない |
