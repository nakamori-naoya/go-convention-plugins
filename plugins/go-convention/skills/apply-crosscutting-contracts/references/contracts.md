# 横断的関心事の型の契約

本文で示す契約の Go の形をまとめる。

## tx.Manager と tx.Options

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

## rdb.Executor

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

## rdb.Translate

```go
// Constraints は、制約（一意、外部キー、CHECK）の名前から具体エラーへの対応である。例: "loans_book_active_key" → domain.ErrBookOnLoan。
type Constraints map[string]*errors.Error

func Translate(ctx context.Context, err error, constraints Constraints) error
```

## clock.Clock と idgen.Generator

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

## errors.HandlingOf と log.Level

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
