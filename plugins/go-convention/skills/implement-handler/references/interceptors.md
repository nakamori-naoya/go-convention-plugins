# interceptor

**interceptor は 2 つ。最外の `Logging` が 1 リクエストの Scope を作り、panic を recover し、返った error と ctx の属性から 1 回だけ記録し、翻訳表で `connect.Code` へ写す。内側の `Auth` が呼び手の主体を確かめて Scope に書く。** server 実装（[connect-server.md](connect-server.md)）はどちらも知らず、error を返すだけである。

## 1. 構成と順序

```
要求 ─▶ Logging ─▶ Auth ─▶ ReservationServer.ConfirmReservation ─▶ usecase
         │  Scope を作る       │  主体を Scope へ                      │
         │  recover            │  無ければ Unauthenticated             │
         │  ログ 1 回          │                                        │
         │  翻訳表で Code      ◀──── error ────────────────────────────┘
応答 ◀───┘
```

| 位置 | interceptor | 責務 | 書く error |
|---|---|---|---|
| 最外 | `Logging(logger)` | `reqctx.Scope` の生成、`recover`、RPC 1 回につきログ 1 行、`toConnectError` による翻訳 | `*connect.Error`（翻訳の結果と、panic の `Internal`） |
| 内側 | `Auth(verifier)` | `Authorization` ヘッダから主体を得て `Scope.Caller` に書く。主体が無ければ拒む | `*connect.Error`（`Unauthenticated`） |

`connect.WithInterceptors(Logging(logger), Auth(verifier))` の順で登録する（先頭が最外）。並びを変えるのは [wiring.md](wiring.md) §3 の `NewMux` だけ。

| 規則 | 理由 |
|---|---|
| recover・ログ・翻訳は 1 つの interceptor | 翻訳の結果（Code）がログのレベルを決める。分けると Code を interceptor 間で受け渡すか、翻訳前の error を失うかのどちらかになる。recover を別にすると、panic を error にした側と記録する側が分かれる |
| `Logging` が最外 | Scope は最外が作らないと内側が書けない（内側の `context.WithValue` は外へ戻らない）。`Auth` の `Unauthenticated` も `Logging` が記録する |
| 認証は interceptor に置く | Scope に主体を書くのは `Logging` の内側でしか成り立たない。認証だけを HTTP middleware に出すと Scope が 2 か所で作られる |
| 翻訳表は `handler` package に 1 つ | 同じ sentinel が RPC ごとに違う Code になる事故を無くす。表の中身（どの sentinel をどの Code にするか）はエラーの規約が決める |
| 認証不要の endpoint は Connect の外に置く | ヘルスチェックは `mux.Handle("GET /healthz", ...)` で、interceptor の chain を通らない。`Auth` に「この Procedure は通す」の表を持たせない |

## 2. `reqctx.Scope`

ctx で運ぶのは logger ではなく、記録する属性の元になる値である。

`reqctx/scope.go`:

```go
package reqctx

import "context"

// Scope は 1 リクエストの間だけ生きる属性の入れ物。最外の interceptor が作り、内側が埋める。
type Scope struct {
	RequestID string
	Caller    string // 認証の interceptor が書く顧客 ID。認証前は空
}

type key struct{}

func New(ctx context.Context, requestID string) (context.Context, *Scope) {
	s := &Scope{RequestID: requestID}
	return context.WithValue(ctx, key{}, s), s
}

func From(ctx context.Context) (*Scope, bool) {
	s, ok := ctx.Value(key{}).(*Scope)
	return s, ok
}
```

`request_id` と `caller` をすべてのログ行に付けるのは、ctx から読んで属性を足す `slog.Handler` のラッパ（`applog.New` が組む）の仕事で、ログの規約が定める。この規約は Scope を作る場所と書く場所だけを決める。

## 3. `Logging`

`handler/logging_interceptor.go`:

```go
package handler

import (
	"context"
	"crypto/rand"
	"log/slog"
	"runtime/debug"
	"time"

	"connectrpc.com/connect"

	"example.com/roomflow/reqctx"
)

// Logging は最外の interceptor。Scope を作り、panic を recover し、RPC 1 回につき 1 行記録し、返った error を connect.Code へ翻訳する。
func Logging(logger *slog.Logger) connect.UnaryInterceptorFunc {
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (res connect.AnyResponse, err error) {
			start := time.Now()
			ctx, _ = reqctx.New(ctx, rand.Text())
			procedure := slog.String("procedure", req.Spec().Procedure)

			defer func() {
				p := recover()
				if p == nil {
					return
				}
				// panic は error 鎖に載らないので、ここが唯一の記録点。応答は固定文言の Internal
				logger.LogAttrs(ctx, slog.LevelError, "RPC が panic した",
					procedure,
					slog.Any("panic", p),
					slog.String("stack", string(debug.Stack())),
				)
				res, err = nil, connect.NewError(connect.CodeInternal, errInternal)
			}()

			res, err = next(ctx, req)
			duration := slog.Int64("duration_ms", time.Since(start).Milliseconds())
			if err == nil {
				logger.LogAttrs(ctx, slog.LevelInfo, "RPC が完了した", procedure, duration)
				return res, nil
			}

			cerr := toConnectError(err)
			logger.LogAttrs(ctx, levelOf(cerr.Code()), "RPC が失敗した",
				procedure,
				duration,
				slog.String("code", cerr.Code().String()),
				slog.Any("err", err), // 翻訳前の error。内部の原因はログにだけ残り、応答には出ない
			)
			return nil, cerr
		}
	}
}

// levelOf は Code からレベルを決める。Code → レベルの表はログの規約が持つ。
func levelOf(code connect.Code) slog.Level {
	switch code {
	case connect.CodeInternal, connect.CodeUnknown, connect.CodeDataLoss, connect.CodeUnimplemented:
		return slog.LevelError
	case connect.CodeAborted, connect.CodeUnavailable, connect.CodeDeadlineExceeded, connect.CodeResourceExhausted:
		return slog.LevelWarn
	}
	return slog.LevelInfo
}
```

| 規則 | 理由 |
|---|---|
| RPC 1 回につきログ 1 行（成功も失敗も） | 内側（usecase・リポジトリ・ドメイン）は error を返すだけで記録しない。境界で 1 回にすると二重ログが消える |
| 記録する `err` は翻訳前、返す error は翻訳後 | 翻訳後の `Internal` には原因が無い。記録は原因、応答は固定文言 |
| `request_id` は最外が `crypto/rand.Text` で採番する | 上流の ID を引き継ぐかは上位の規約が決める。「ヘッダにあれば使い、無ければ採番」の分岐を書かない |
| 属性は `procedure` / `duration_ms` / `code` / `err` / `panic` / `stack` だけ | 語彙はログの規約の表。要求の本文（予約番号・顧客 ID）は interceptor では読めないし読まない。業務 ID は usecase の途中ログの関心 |
| `logger` は引数で受ける。`slog.Default()` に倒さない | `nil` を既定へ丸めると、組み立ての誤りが「ログが出ない」として現れる。組み立てで必ず渡す |

## 4. `Auth`

`handler/auth_interceptor.go`:

```go
package handler

import (
	"context"
	"errors"

	"connectrpc.com/connect"

	"example.com/roomflow/reqctx"
)

// Verifier は認証情報から呼び手の顧客 ID を得る。検証方式（トークンの形・署名・失効）は上位の規約が決める。
// 返す error は利用者に見せられる文言の sentinel にする（Auth がそのまま Unauthenticated の文言にする）。
type Verifier interface {
	Verify(ctx context.Context, authorization string) (customerID string, err error)
}

var (
	errNoAuthorization = errors.New("認証情報の無い要求は受け付けない")
	errNoScope         = errors.New("リクエストの Scope が ctx に無い") // 組み立ての誤り（Logging が外側に無い）。Internal
)

// Auth は Authorization ヘッダの主体を確かめ、Scope.Caller に書く。主体が無ければ Unauthenticated。記録はしない（Logging が拾う）。
func Auth(v Verifier) connect.UnaryInterceptorFunc {
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			authorization := req.Header().Get("Authorization")
			if authorization == "" {
				return nil, connect.NewError(connect.CodeUnauthenticated, errNoAuthorization)
			}
			customerID, err := v.Verify(ctx, authorization)
			if err != nil {
				return nil, connect.NewError(connect.CodeUnauthenticated, err)
			}
			s, ok := reqctx.From(ctx)
			if !ok {
				return nil, errNoScope
			}
			s.Caller = customerID
			return next(ctx, req)
		}
	}
}
```

| 規則 | 理由 |
|---|---|
| 主体が無ければ `Unauthenticated` を返し、`next` を呼ばない | 主体の無い要求を usecase まで通すと、`callerFrom` の `Internal` として現れ、利用者に「認証していない」と伝わらない |
| `Auth` は `connect.NewError` を自分で書く | `Unauthenticated` / `PermissionDenied` は認証の関心で、翻訳表の sentinel ではない。`toConnectError` は `*connect.Error` を素通しする |
| 本人かどうか（`ErrNotOwner`）は `Auth` で判断しない | 予約の所有者は集約が知っている。`Auth` は「誰か」だけを決め、「その人がこの予約を触れるか」は集約が `Cancel(at, by)` で拒む |
| `Scope` が無ければ `errNoScope`（`Internal`） | `Logging` の内側にしか置けない。無いのは `NewMux` を通さずに組み立てた誤りで、既定の Scope を作って続けない |
| Verifier の error は sentinel | 文言がそのまま応答に出る。検証ライブラリの error を包まずに返すと、内部の情報が利用者に見える |

## 5. 翻訳表

`handler/error_table.go`:

```go
package handler

import (
	"context"
	"errors"

	"connectrpc.com/connect"

	"example.com/roomflow/query"
	"example.com/roomflow/rdb"
	"example.com/roomflow/reservation"
)

// codeTable は error を connect.Code へ写す唯一の対応表。上から順に errors.Is で引く。
// どの sentinel をどの Code にするかはエラーの規約が決める。ここには題材の分だけ置く。
var codeTable = []struct {
	err  error
	code connect.Code
}{
	// 本人でない
	{reservation.ErrNotOwner, connect.CodePermissionDenied},
	// 事前条件・状態違い・重なり: 今の状態では受け付けない
	{reservation.ErrHoldDeadlinePassed, connect.CodeFailedPrecondition},
	{reservation.ErrAlreadyConfirmed, connect.CodeFailedPrecondition},
	{reservation.ErrAlreadyCancelled, connect.CodeFailedPrecondition},
	{reservation.ErrAlreadyExpired, connect.CodeFailedPrecondition},
	{reservation.ErrSlotAlreadyStarted, connect.CodeFailedPrecondition},
	{reservation.ErrOverlappingSlot, connect.CodeFailedPrecondition},
	{reservation.ErrCustomerSuspended, connect.CodeFailedPrecondition},
	// 入力不正: 値オブジェクトの生成の条件、handler が検出した欠け、読み取りモデルの引数の形
	{reservation.ErrIDRequired, connect.CodeInvalidArgument},
	{reservation.ErrRoomCodeRequired, connect.CodeInvalidArgument},
	{reservation.ErrTimeSlotNotOrdered, connect.CodeInvalidArgument},
	{ErrStartsAtRequired, connect.CodeInvalidArgument},
	{ErrEndsAtRequired, connect.CodeInvalidArgument},
	{query.ErrDayHasClock, connect.CodeInvalidArgument},
	{query.ErrPageLimitOutOfRange, connect.CodeInvalidArgument},
	{query.ErrPageOffsetNegative, connect.CodeInvalidArgument},
	// 永続化と読み取りモデル
	{rdb.ErrNotFound, connect.CodeNotFound},
	{query.ErrNotFound, connect.CodeNotFound},
	{rdb.ErrConflict, connect.CodeAborted},
	// 呼び手の中断
	{context.Canceled, connect.CodeCanceled},
	{context.DeadlineExceeded, connect.CodeDeadlineExceeded},
}

// toConnectError は返った error を *connect.Error にする。表に無ければ Internal と固定文言。
func toConnectError(err error) *connect.Error {
	if cerr, ok := errors.AsType[*connect.Error](err); ok {
		return cerr // Auth が作った Unauthenticated など。二重に翻訳しない
	}
	for _, row := range codeTable {
		if errors.Is(err, row.err) {
			return connect.NewError(row.code, row.err)
		}
	}
	return connect.NewError(connect.CodeInternal, errInternal)
}
```

| 規則 | 理由 |
|---|---|
| 応答の文言は sentinel の文言だけ（`connect.NewError(code, row.err)`）。包んだ文脈（`予約 R-1 の確定: ...`）は出さない | 文脈は運用者向けで、ログが持つ。利用者は自分が何を求めたか知っている |
| 表に無い error は `Internal` と `errInternal` | SQL・接続先・外部ライブラリの文言を外に出さない。表に載せるかは、その sentinel を足したときに決める |
| `errNoCaller` / `errNoScope` / `reservation.ErrEligibilityMismatch` / `rdb.ErrNoTransaction` は表に載せない | 利用者の入力では起きない。組み立てか usecase の誤りで、`Internal` として記録され、直すのは実装者 |
| 表は `errors.Is` で上から順に引く | 型付き error も `Is` で sentinel に答える。表に型を足さない |
| `*connect.Error` は素通し | 既に Code を持つ error（`Auth` の `Unauthenticated`）を `Internal` に潰さない |
| `reservation.ErrCustomerIDRequired` は表に載せない | `CustomerID` は主体から来る。空なら `callerFrom` が先に止めるので、ここに届くのは誤り |
| handler の欠け sentinel は公開（`ErrStartsAtRequired`）で表に載せる | 入口のテストが `errors.Is` で突き合わせる。文言は利用者に見せるものなので、そのまま応答になる |
| 読み取りモデルの sentinel（`query.ErrNotFound` / `ErrDayHasClock` / `ErrPageLimitOutOfRange` / `ErrPageOffsetNegative`）も表に載せる | 読み取り RPC も同じ interceptor を通る。載せないと `Internal` になり、利用者の入力不正が内部エラーとして記録される |

## 6. server 実装に書かないこと

| 書かない | どこがやるか |
|---|---|
| `slog.*` | `Logging` が返った error と Scope から 1 行 |
| `connect.NewError(...)` | `toConnectError`（翻訳表）と `Auth` |
| `errors.Is(err, reservation.ErrNotOwner)` の分岐 | 翻訳表 |
| `recover()` | `Logging` |
| `req.Header().Get("Authorization")` | `Auth` |
| `if caller != in.CustomerID` | 集約（`Confirm(at, by)` が `ErrNotOwner`） |
