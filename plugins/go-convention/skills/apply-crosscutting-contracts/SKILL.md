---
name: apply-crosscutting-contracts
description: Go の横断的関心事（tx.Manager と tx.Options、ctx の rdb.Executor、読み取り専用の接続、rdb.Translate、clock.Clock、idgen.Generator、errors.HandlingOf、log.Level）の定義と振る舞いを一か所で定め、それに沿って置く・使う。「横断的関心事の package を作って」「tx の張り方を知りたい」「Translate の契約は」と言われたとき、また層の skill がこれらを使うときに使う。
---

# apply-crosscutting-contracts

層の skill は、ここに書いた契約だけを前提にし、例のコードから契約を推測しない。横断的関心事は `internal/crosscutting/<目的>` に目的ごとに一つの package で置き、業務の概念を import しない。公開するのは下の契約とその本番の実装だけにする。便利な操作を足すと、どの層からでも何でもできる置き場になり、層の線が消えるからである。

## トランザクション：`tx.Manager` と `tx.Options`

```go
package tx

// Manager は、fn を一つのトランザクションの中で実行する。参加できるのは PostgreSQL だけである。
type Manager interface {
	Run(ctx context.Context, opts Options, fn func(ctx context.Context) error) error
}

// Options は、物理設計の資料が操作ごとに決めた指定である。ゼロ値は「指定が無い」を表す。
type Options struct {
	Isolation  Isolation // ReadCommitted、RepeatableRead、Serializable（封じた型）
	RetryOn    Retry     // やり直す失敗。SerializationFailure など（封じた型）。ゼロ値はやり直さない
	MaxRetries int       // RetryOn に当たったとき、fn を最初から呼び直す上限の回数
}
```

`Run` は、分離レベルの無い `Options` と、ctx に既にトランザクションがある呼び出し（入れ子）を、張らずに分類不能で返す。既定の分離レベルや回数に頼ると、物理設計の指定の渡し忘れに誰も気付かないからである。

`Run` は張ったトランザクションを `rdb.WithExecutor` で ctx に載せて fn を呼び、nil なら確定する。エラーか panic なら取り消し、panic はそのまま伝え、取り消しの失敗は戻り値に載せずに注入された logger で記録する。確定を送った後に応答を受けずに接続が切れたか期限が切れたときは、確定したか分からないので「回復不能」を返す。再処理させると二重に成立しうるからである。

`RetryOn` に当たる失敗は、`MaxRetries` まで fn を最初から呼び直す。だから fn の中で採番せず、外部との通信もしない。採番は呼び直しで別の値になり、外部への通信は取り消せないからである。usecase にやり直しのループを書かない。

## ctx が運ぶトランザクション：`rdb.Executor`

```go
package rdb

// Executor は、トランザクションの中で読み書きする。sqlc の DBTX を満たす。
type Executor interface {
	Exec(ctx context.Context, sql string, args ...any) (pgconn.CommandTag, error)
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// ErrNoTransaction は、トランザクションの無い ctx から Executor を求めた呼び方の間違いで、分類不能を土台にする。
var ErrNoTransaction = errors.Define(errors.ErrUnclassified, "コンテキストにトランザクションが無い")

func WithExecutor(ctx context.Context, e Executor) context.Context
func ExecutorFromContext(ctx context.Context) (Executor, error)
```

`WithExecutor` を呼ぶのは `tx.Manager` の実装だけである。リポジトリと手順の口は `ExecutorFromContext` から sqlc の `Queries` を組み、無ければそのエラーを返して pool に切り替えない。切り替えると、張り忘れが黙って通るからである。Query の実装は ctx を見ず、各接続の既定を読み取り専用（`default_transaction_read_only=on`）にした pool を、`Exec` だけが分類不能の `ErrWriteInReadOnly` を返す `ReadExecutor` で包んで使う。

## 外部のエラーの翻訳：`rdb.Translate`

```go
// Constraints は、一意制約の名前から具体エラーへの対応である。例: "loans_book_active_key" → domain.ErrBookOnLoan。
type Constraints map[string]*errors.Error

func Translate(ctx context.Context, err error, constraints Constraints) error
```

pgx を呼んだ場所は、返ったエラーを必ず `Translate` に通す。`Translate` は handle-errors の PostgreSQL の翻訳表で分類へ写し、分類を外側、元のエラーを内側に包む。分類済みのエラーと ctx の中断と期限切れは包み直さない。一意制約の違反は `constraints` で具体エラーへ写し、載っていなければ分類不能にする。表に無いエラーは変えずに返し、どの分類にも丸めない。境界が分類不能として記録するので、それを見て表に足す。ctx は、呼び出し側の都合か依存先の不調かを見分けるためだけに使う。入力の値を含みうる文言（Detail、Hint）は落としてから連鎖に残す。

## 時計と採番器：`clock.Clock` と `idgen.Generator`

```go
package clock

//go:generate go run go.uber.org/mock/mockgen -source=clock.go -destination=mock/clock.go -package=mock_clock

// Clock は、現在時刻を返す。本番の System は UTC で返す。
type Clock interface {
	Now() time.Time
}

package idgen

//go:generate go run go.uber.org/mock/mockgen -source=generator.go -destination=mock/generator.go -package=mock_idgen

// Generator は、業務の概念をまだ持たない UUID を返す。例: "0193a3c1-7a4e-7c2e-9f10-5b8d2e6a4f01"（UUIDv7）。
type Generator interface {
	NewID() uuid.UUID
}
```

どちらも差し替えるためだけにある技術の境界なので、interface はここに一つだけ置き、mock はここの `mock/` に生成し、使う側で切り直さない。採番器は識別子の種類ごとに増やさず、使う側がその場で識別子の値オブジェクトへ変換する。`time.Now()` を本文で直接呼ばない。誰がいつ時刻を取り採番するかは、development-convention の `apply-layer-convention` が決めている。

## 分類の表を引く関数：`errors.HandlingOf` と `log.Level`

```go
package errors

// Handling は、失敗を受けた処理が次に何をするかを決める二つの性質である。
type Handling struct {
	Reprocessable bool // 同じ要求をもう一度処理すれば通る見込みがある
	Spreads       bool // 同じ処理の残りの件も同じ理由で失敗する
}

func HandlingOf(err error) (Handling, bool)

package log

func Level(err error) (slog.Level, bool)
```

どちらも err の分類（`errors.Category`）で表を引き、表に分類が無ければ false を返して既定の値へ丸めない。false を受けた呼び手は、表の更新漏れ（実装の間違い）として扱う。境界なら分類不能の応答と ERROR と `unclassified` の属性で記録し、一件ずつ処理するループなら残りを試さずに返す。

表の中身は、処理の表と応答の表を handle-errors が、ログレベルの表を write-logs が持ち、互いに導かない。表が15の分類を過不足なく持つことは、分類の定義と表の行を突き合わせるプロジェクト固有の lint で守り、分類の一覧を返す関数を公開しない。
