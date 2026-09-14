# 基本

**失敗を隠さず、原因の行を読み手の近くに置く。** ここに並ぶ規則はすべてこの一点のためにある。関数の形（返り値・引数・レシーバ）、分岐の形、初期化の形を一つに揃え、「なぜこの値になったか」を辿らずに済むコードにする。

例の題材は貸会議室予約（module `example.com/roomflow`）。ディレクトリ構成は上位の開発規約が決めるので、例は import path を短くするため package を平らに置いている。

## 1. 明示を選ぶ。暗黙の変換・暗黙の既定・魔法の初期化をしない

**する:** 値がどこから来たかをコードの行で示す。変換は名前のある関数を呼ぶ。既定値は呼び出し側が書く。
**しない:** 型変換・既定値の補完・初期化を、読み手が知らない場所（`init`、struct のゼロ値の特別扱い、埋め込みによるメソッドの昇格、`String()` による暗黙の文字列化）で起こす。

```go
// しない: ゼロ値を「未設定なら 15 分」と読み替える。読み手は HoldDeadline の実装を見ないと 15 分が分からない
func NewHoldDeadline(heldAt time.Time, ttl time.Duration) HoldDeadline {
	if ttl == 0 {
		ttl = 15 * time.Minute
	}
	return HoldDeadline{at: heldAt.Add(ttl)}
}

// する: 規則を名前のある定数にし、関数は引数から結果を作るだけにする
const holdTTL = 15 * time.Minute

func NewHoldDeadline(heldAt time.Time) HoldDeadline {
	return HoldDeadline{at: heldAt.UTC().Add(holdTTL)}
}
```

理由: 暗黙の動作は失敗の原因を、失敗した行から遠い場所へ移す。「この値はなぜ 15 分後なのか」を答えるために実装を辿る時間が、暗黙 1 つごとに増える。

## 2. 未指定・不正値を既定値に丸めない

**する:** 受け取った値が条件を満たさなければ `error` を返す。何が拒まれたかを sentinel で示す（sentinel の定義と文言はエラーの規約が決める）。
**しない:** 「無ければ 0」「不正なら既定へ」「範囲外なら端に寄せる」を書く。

```go
// しない: 不正値を 1 に丸める。呼び出し側は「1 を渡した」のか「不正値が丸められた」のか区別できない
func NewVersion(n int) Version {
	if n < 1 {
		n = 1
	}
	return Version{v: n}
}

// する: 拒む
var ErrVersionNotPositive = errors.New("1 未満の版は作れない")

func NewVersion(n int) (Version, error) {
	if n < 1 {
		return Version{}, ErrVersionNotPositive
	}
	return Version{v: n}, nil
}
```

理由: 丸めは失敗を成功に見せる。DB の行が壊れていても、入力が欠けていても、丸めた瞬間に痕跡が消え、別の場所で「なぜかこの値」として現れる。

## 3. フォールバックを書かない

**する:** 一次手段が失敗したら `error` を返し、境界（handler / worker）で記録して終える。どうしてもフォールバック（別の手段で続行する分岐）が要ると判断したら、**書く前に利用者へ理由と代替手段を示して許可を得る。** 許可の無いフォールバックは書かない。
**しない:** 「A が失敗したら B を試す」「設定が読めなければ組み込みの値で起動する」「キャッシュが無ければ空として続行する」を自分の判断で書く。

```go
// しない: 設定ファイルが無いときに既定の接続先で続行する。本番で設定を置き忘れても起動してしまう
func loadDSN(path string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return "postgres://localhost:5432/roomflow"
	}
	return string(b)
}

// する: 読めなければ失敗を返し、起動を止める
func loadDSN(path string) (string, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("接続設定 %s の読み取り: %w", path, err)
	}
	return string(b), nil
}
```

理由: フォールバックは「失敗したのに動いている」状態を作り、失敗を発見する時点を最も遠く（利用者からの問い合わせ）へ押しやる。要るかどうかの判断は業務と運用の判断であって、コードを書いている最中に決めることではない。

## 4. 分岐はガード節で書き、`else` の入れ子を作らない

**する:** 拒む条件を先に並べて `return` し、本筋を字下げ無しで最後に書く。
**しない:** `if ok { ... } else { ... }` を重ねる。`else` の中に本筋を置く。

```go
// しない: 本筋が最も深い字下げにある
func (t Tentative) Confirm(at time.Time, by CustomerID) (ConfirmResult, error) {
	if !t.deadline.HasArrived(at) {
		if by == t.customer {
			at = at.UTC()
			v := t.version.Next()
			return ConfirmResult{
				Next:  Confirmed{core: t.core.withVersion(v)},
				Event: ConfirmedEvent{base: base{reservationID: t.id, version: v, occurredAt: at}, by: by},
			}, nil
		} else {
			return ConfirmResult{}, ErrNotOwner
		}
	} else {
		return ConfirmResult{}, ErrHoldDeadlinePassed
	}
}

// する: 拒む条件が資料の順（期限 → 本人）に上から読め、本筋は 1 段目にある
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

理由: ガード節は「拒む理由」と「拒む行」を隣り合わせにする。失敗時のスタックトレースの行番号がそのまま理由を指す。`else` の入れ子は条件の否定を頭の中で組み合わせないと本筋の前提が分からない。

## 5. 返り値は最大 2 つ

**する:** `(T, error)` か `(T, bool)`。3 つ目が要るなら結果 struct を 1 つ返す。
**しない:** `(T, U, error)`、`(T, bool, error)`、`(int, int, int)`。

```go
// しない
func (t Tentative) Confirm(at time.Time, by CustomerID) (Confirmed, ConfirmedEvent, error)

// する: 結果 struct（題材では generic な遷移結果型を型エイリアスで名付ける）
type Transition[S Reservation, E Event] struct {
	Next  S
	Event E
}

type ConfirmResult = Transition[Confirmed, ConfirmedEvent]

func (t Tentative) Confirm(at time.Time, by CustomerID) (ConfirmResult, error)
```

`(T, bool)` は「拒まないが何も変えないことがある」操作（`Expire` / `RecordNoShow`）と、存在の問い合わせ（`NoShowAt() (time.Time, bool)`）に使う。`(T, error)` は拒む理由があるとき。両方が要る操作は設計を分ける。

理由: 返り値が 3 つ以上になると、呼び出し側で `_` が増えて「何を捨てたか」が読めなくなる。結果 struct はフィールド名が説明になり、フィールドを足しても呼び出し側が壊れない。

## 6. naked return を書かない

**する:** `return x, err` と明示する。名前付き結果は `defer` で結果を書き換えるときだけ使い、そのときも `return` には値を書く。
**しない:** `return` だけの行。名前付き結果を「ドキュメント代わり」に使う。

```go
// する: defer が err を更新するので名前付き結果。それでも return は明示する
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
		return err
	}
	if err := t.Commit(ctx); err != nil {
		return fmt.Errorf("トランザクションのコミット: %w", err)
	}
	return nil
}
```

`defer` の閉包は結果を持たないので、その中の `return` は naked return ではない（ガード節の早期リターン）。

理由: naked return は「この行で何が返るか」を関数の先頭まで戻って読ませる。関数が長くなるほど、途中の代入がどの結果に効いているかを追えなくなる。

## 7. `context.Context` は第一引数。struct に持たない

**する:** `func (u *ConfirmReservation) Execute(ctx context.Context, in ConfirmReservationInput) error`。名前は `ctx`。
**しない:** `type Service struct{ ctx context.Context }`。`context.Background()` を関数の途中で作って親の ctx を捨てる。`context.TODO()` を残す。

```go
// しない: ctx を捨てる
func (r *ReservationRepository) FindByID(ctx context.Context, id reservation.ID) (reservation.Reservation, error) {
	row, err := r.q.FindReservation(context.Background(), id.Value())

// する
	row, err := r.q.FindReservation(ctx, id.Value())
```

理由: ctx は呼び出しの寿命（キャンセル・期限）である。struct に持たせると寿命が呼び出しと合わなくなり、途中で作り直すとキャンセルが伝わらない。ドメインの型（値オブジェクト・集約）は ctx を受け取らない。I/O をしないからである。

## 8. 引数が 4 つを超えるなら struct

**する:** 呼び出し側で意味を読める名前の struct（`{操作}Input` / `{操作}Params`）。フィールド名で渡す。
**しない:** 同じ型の引数を 5 つ並べる。`opts ...Option` を業務の入力に使う。

```go
type ConfirmReservationInput struct {
	ReservationID string
	CustomerID    string
	At            time.Time
}

func (u *ConfirmReservation) Execute(ctx context.Context, in ConfirmReservationInput) error
```

ドメインの操作（`Hold(id, customer, slot, eligibility, at)`）は資料の操作と 1:1 なので、5 つでも引数のまま置く。引数を struct にまとめるかはドメインモデルの規約が決める。

理由: 同じ型が並ぶと入れ違いをコンパイラが検出できない。struct はフィールド名が呼び出し側に残る。

## 9. 値渡しが既定。ポインタは「変更が要る」「nil が意味を持つ」ときだけ

**する:** 値オブジェクト・集約の状態型・イベント・DTO・入力 struct・結果 struct は値で受け渡す。コンストラクタは値を返す。interface・スライス・map・チャネル・関数は値渡しで足りる（中身が参照）。
**しない:** サイズや速度を理由にポインタを選ぶ（実測してからにする）。`*string` で「未指定」を表す（`(T, bool)` か専用の型にする）。

ポインタにするのは次の 2 つだけ。

| 場合 | 例 |
|---|---|
| メソッドが自分の状態を変える型。接続・プール・キャッシュ・カウンタを持つ協力者 | `NewReservationRepository() *ReservationRepository`、`*tx.Manager`、`*usecase.ConfirmReservation`、`*pgxpool.Pool` |
| `nil` が「無い」を意味する引数で、呼び出し側がその意味を知っている | `reservationRowToReservation(res sqlcgen.Reservation, deadline *sqlcgen.TentativeHoldDeadline, noShowAt []time.Time)` — 仮予約でなければ `deadline` は `nil`（`noShowAt` はスライスなので 0 件は nil のまま渡す） |

ポインタを受け取る関数は先頭で `nil` を扱う（ガード節）。

理由: 値は共有されないので、渡した先で書き換えられる心配が無い。ポインタが増えると「誰がいつ変えたか」と「nil か」の 2 つを常に考えることになる。

## 10. レシーバは型の中で統一する

**する:** 型ごとに値レシーバかポインタレシーバのどちらかに揃える。不変の型（値オブジェクト・状態型・イベント）は値レシーバで、操作は新しい値を返す。状態を変える型（リポジトリ実装・usecase・`tx.Manager`）はポインタレシーバ。
**しない:** 同じ型に値レシーバとポインタレシーバを混ぜる。`sync.Mutex` を持つ型を値レシーバにする（`copylocks` が落とす）。

```go
func (t Tentative) Confirm(at time.Time, by CustomerID) (ConfirmResult, error) // 値レシーバ。新しい値を返す
func (r *ReservationRepository) FindByID(ctx context.Context, id reservation.ID) (reservation.Reservation, error) // ポインタレシーバ
```

理由: 混ざると、その型の値がメソッド集合をどこまで満たすかが呼び出し側で変わり、interface を満たすかどうかがポインタか値かで分かれる。

## 11. struct リテラルはフィールド名付き

**する:** `Transition[Confirmed, ConfirmedEvent]{Next: next, Event: evt}`。
**しない:** `Transition[Confirmed, ConfirmedEvent]{next, evt}`。

例外は、フィールドが 1 つで型名が意味を示す封じた struct の package 変数（`KindTentative = Kind{"tentative"}`）だけ。

理由: 位置指定はフィールドの追加・並べ替えで静かに意味が変わる。`go vet` の `composites` は他 package の型だけを検査するので、同 package では規則で守る。

## 12. `init` を書かない。package 変数は定数と同じものだけ

**する:** package 変数に置くのは、sentinel（`var ErrNotOwner = errors.New(...)`）、`regexp.MustCompile` の結果、封じた列挙の値、のように「一度作れば変わらず、失敗しない」ものだけ。それ以外の初期化（接続・設定の読み込み・登録）は `main` の `run` から明示的に呼ぶ。
**しない:** `func init()`。package 変数に接続やクライアントを置く。可変の package 変数（グローバルな map・カウンタ）。

理由: `init` は import した瞬間に走り、順序が import グラフで決まり、失敗を返せない。読み手はどこから呼ばれたのか辿れない。テストでも差し替えられない。

## 13. `main` は `run(ctx) error` を呼んで `os.Exit`

**する:** `main` は次の形だけ。組み立て（DI）、起動、停止待ち、後始末の `defer` は `run` に書く。シグナルは `signal.NotifyContext` で ctx に変える。
**しない:** `main` にロジックや `defer` を書く（`os.Exit` は `defer` を実行しない）。`os.Exit` を `main` 以外で呼ぶ。`log.Fatal*` を呼ぶ（`TestMain` を除く。`main` は `run` の error を `os.Stderr` に出して `os.Exit(1)` する）。

```go
package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	err := run(ctx)
	stop()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(ctx context.Context) error {
	// 設定の読み取り → 接続 → DI の組み立て → サーバ起動 → ctx.Done() まで待つ → 停止
	return nil
}
```

`signal.NotifyContext` が返す ctx は Go 1.26 から受け取ったシグナルを `context.Cause(ctx)` で読める。停止理由を記録するときはこれを使う。

理由: `run` が `error` を返すので、起動失敗が 1 か所（`main`）で終了コードになり、`run` の `defer` が全部走ってから終わる。テストから `run` を呼べる。

## 14. ファイル内の宣言順

**する:** 定数 → 型 → コンストラクタ（`New*` / `Restore*`） → 状態を変える公開メソッド → getter → 非公開の関数・メソッド。型が複数あるなら型ごとにこの塊を並べ、非公開はファイル末尾にまとめる。sentinel の `var (...)` は package の `errors.go` に置く。
**しない:** getter を先頭に置く。非公開関数を公開メソッドの間に挟む。

理由: 上から読むだけで「この型は何ができるか」が分かる。実現方法（非公開）は読まなくても済む。
