# middleware が拾って出す

**handler に手動ログを増やさない。最外の interceptor が、返ったエラーと ctx の属性から 1 回だけ記録する。** 記録に要る値は「ctx に載せた属性の元」と「返ったエラー」の 2 つだけにし、内側はその 2 つを整えることに専念する。

題材のディレクトリは import path を短くするため平らにしている（`example.com/roomflow/{reservation,rdb,query,tx,usecase,handler,worker,reqctx,applog}`）。実際の配置は上位の開発規約が決める。

## 1. ctx から属性を足す handler

ctx で運ぶのは logger ではなく、**属性の元になる値**である。最外の interceptor が 1 リクエスト分の入れ物を作って ctx に載せ、内側の interceptor（認証・認可）がそこへ書く。`slog.Handler` のラッパが `Handle` のたびに ctx から読んで属性を足すので、途中ログを含むすべての行に `request_id` と `caller` が付く。

```go
package reqctx

import "context"

// Scope は 1 リクエストの間だけ生きる属性の入れ物。最外の interceptor が作り、内側が埋める。
type Scope struct {
	RequestID string
	Caller    string // 認証 interceptor が埋める。認証前は空
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

```go
package applog

import (
	"context"
	"io"
	"log/slog"

	"example.com/roomflow/reqctx"
)

// New は JSON handler に秘匿の安全網と ctx 属性を重ねた logger を返す。run が 1 回だけ呼ぶ。
func New(w io.Writer, level slog.Leveler) *slog.Logger {
	json := slog.NewJSONHandler(w, &slog.HandlerOptions{Level: level, ReplaceAttr: redact})
	return slog.New(ctxHandler{Handler: json})
}

type ctxHandler struct{ slog.Handler }

func (h ctxHandler) Handle(ctx context.Context, rec slog.Record) error {
	if s, ok := reqctx.From(ctx); ok {
		rec = rec.Clone() // 受け取った Record は共有状態を持つ。複製してから足す
		rec.AddAttrs(slog.String("request_id", s.RequestID))
		if s.Caller != "" {
			rec.AddAttrs(slog.String("caller", s.Caller))
		}
	}
	return h.Handler.Handle(ctx, rec)
}

// WithAttrs / WithGroup を包み直さないと logger.With の結果からラッパが外れる。
func (h ctxHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return ctxHandler{Handler: h.Handler.WithAttrs(attrs)}
}

func (h ctxHandler) WithGroup(name string) slog.Handler {
	return ctxHandler{Handler: h.Handler.WithGroup(name)}
}
```

`redact` は [redaction.md](redaction.md) §4。`Enabled` は埋め込んだ handler のものがそのまま使われる。

| 規則 | 理由 |
|---|---|
| logger を ctx に入れない | ctx に logger があると「どこでも書ける」になり、[boundaries.md](boundaries.md) §2 の層の線が消える |
| 入れ物は最外が作る | 内側の `context.WithValue` は外側へ戻らない。外側が記録するとき内側が足した値を読むには、外側が作ったポインタへ内側が書くしかない |
| ラッパは `WithAttrs` / `WithGroup` も実装する | 埋め込みで済ませると `logger.With(...)` が返す handler は素の JSON handler になり、以後 `request_id` が付かない |

## 2. Connect の interceptor

RPC 1 回につきログ 1 行。成功は `Info`、失敗は翻訳後の `connect.Code` からレベルを決める（[severity-and-attributes.md](severity-and-attributes.md) §2）。panic はここで recover して stack 付きで記録し、`Internal` を返す。`connect.WithRecover` は使わない（recover を別の機構に分けると、panic を error にした側と記録する側が分かれる）。

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

// levelOf は Code からレベルを決める。表は severity-and-attributes.md §2。
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

翻訳表は `handler/error_table.go` の `codeTable` 1 か所で、当てる関数が `toConnectError`。`Internal` の固定文言は `handler/errors.go` の `errInternal`（`errors.New("内部エラーが発生した")`）で、翻訳表のファイルには置かない。どの sentinel をどの Code にするかはエラーの規約が決めるので、ここでは形と、この規約に関わる 2 点（応答に出すのは sentinel の文言だけ・`Internal` は固定文言）だけを示す:

```go
package handler

import (
	"context"
	"errors"

	"connectrpc.com/connect"

	"example.com/roomflow/rdb"
	"example.com/roomflow/reservation"
)

// codeTable は error を connect.Code へ写す唯一の対応表。上から順に errors.Is で引く。題材の一部だけ示す。
var codeTable = []struct {
	err  error
	code connect.Code
}{
	{reservation.ErrNotOwner, connect.CodePermissionDenied},
	{reservation.ErrHoldDeadlinePassed, connect.CodeFailedPrecondition},
	{reservation.ErrAlreadyConfirmed, connect.CodeFailedPrecondition},
	{reservation.ErrOverlappingSlot, connect.CodeFailedPrecondition},
	{reservation.ErrIDRequired, connect.CodeInvalidArgument},
	{rdb.ErrNotFound, connect.CodeNotFound},
	{rdb.ErrConflict, connect.CodeAborted},
	{context.Canceled, connect.CodeCanceled},
	{context.DeadlineExceeded, connect.CodeDeadlineExceeded},
}

// toConnectError は返った error を *connect.Error にする。表に無ければ Internal と固定文言（handler/errors.go の errInternal）。
func toConnectError(err error) *connect.Error {
	if cerr, ok := errors.AsType[*connect.Error](err); ok {
		return cerr // Auth が作った Unauthenticated など。二重に翻訳しない
	}
	for _, row := range codeTable {
		if errors.Is(err, row.err) {
			return connect.NewError(row.code, row.err) // 応答は sentinel の文言だけ。包んだ文脈は渡さない
		}
	}
	return connect.NewError(connect.CodeInternal, errInternal)
}
```

| 規則 | 理由 |
|---|---|
| 翻訳とログは同じ interceptor | 翻訳の結果（Code）がレベルを決める。別の interceptor に分けると、どちらが記録したかの状態を受け渡す羽目になる |
| レベルは sentinel ではなく Code から決める | sentinel → Code の表はエラーの規約が持ち、Code → レベルの表はログの規約が持つ。1 つの sentinel を 2 つの表に書かない |
| `err` は翻訳前の値、応答は `connect.NewError(row.code, row.err)` | `Internal` に丸めた後の error には原因が無い。記録は原因、応答は sentinel の文言だけ。包んだ文脈（`予約 R-0101 の確定: ...`）を応答に渡すと、運用者向けの連鎖が利用者に見える |
| recover は最外の interceptor 1 か所 | 別の recover 機構を重ねると、panic を error にした側と記録する側が分かれて 2 行になる |
| `request_id` は最外が採番する | `crypto/rand.Text`。上流の ID を引き継ぐかは上位の規約が決める。この interceptor の外で採番された ID を「無ければ採番」で受ける分岐を書かない |

## 3. 内側の interceptor と server 実装は記録しない

認証 interceptor `Auth` は主体を `Scope.Caller` へ書き、失敗は error を返すだけにする。主体が無ければ `Unauthenticated` を返して `next` を呼ばない（黙って続行しない）。外側の `Logging` が `Unauthenticated` を `Info` で 1 回記録する。

`handler/auth_interceptor.go`:

```go
package handler

import (
	"context"
	"errors"

	"connectrpc.com/connect"

	"example.com/roomflow/reqctx"
)

// Verifier は認証情報から呼び手の顧客 ID を得る。返す error は利用者に見せられる文言の sentinel にする。
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

server 実装のメソッドは主体を読み、DTO を変換して usecase を呼び、error をそのまま返す。`slog` を import しない。`connect.NewError` も書かない（要求の欠けは変換関数が sentinel で返し、`codeTable` が `InvalidArgument` に写す）。

```go
func (s *ReservationServer) ConfirmReservation(
	ctx context.Context,
	req *connect.Request[roomflowv1.ConfirmReservationRequest],
) (*connect.Response[roomflowv1.ConfirmReservationResponse], error) {
	caller, err := callerFrom(ctx)
	if err != nil {
		return nil, err
	}
	in := confirmRequestToInput(req.Msg, caller, s.clock.Now())
	if err := s.confirm.Execute(ctx, in); err != nil {
		return nil, err // 記録しない。翻訳しない。Logging が両方やる
	}
	return connect.NewResponse(&roomflowv1.ConfirmReservationResponse{}), nil
}
```

組み立ては `run` が行う。interceptor の並び（`Logging` が最外）は `handler.NewMux(handler.Deps{...})` の 1 か所に閉じ、`run` は環境変数から `Deps` を作って渡すだけである。`run` が作るのは logger と pool と worker で、logger は `Deps.Logger` と worker の両方へ同じものを渡す。

```go
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/applog"
	"example.com/roomflow/auth"
	"example.com/roomflow/clock"
	"example.com/roomflow/handler"
	"example.com/roomflow/worker"
)

const (
	readHeaderTimeout = 10 * time.Second
	shutdownTimeout   = 10 * time.Second
	expireEvery       = time.Minute
)

type config struct {
	DatabaseURL string // DATABASE_URL
	ListenAddr  string // LISTEN_ADDR。":8080" のような待ち受けアドレス。既定値に倒さない
	AuthSecret  string // AUTH_SECRET
}

func requireEnv(name string) (string, error) {
	v := os.Getenv(name)
	if v == "" {
		return "", fmt.Errorf("環境変数 %s が無い", name)
	}
	return v, nil
}

func loadConfig() (config, error) {
	databaseURL, err := requireEnv("DATABASE_URL")
	if err != nil {
		return config{}, err
	}
	listenAddr, err := requireEnv("LISTEN_ADDR")
	if err != nil {
		return config{}, err
	}
	authSecret, err := requireEnv("AUTH_SECRET")
	if err != nil {
		return config{}, err
	}
	return config{DatabaseURL: databaseURL, ListenAddr: listenAddr, AuthSecret: authSecret}, nil
}

// run は logger を 1 つ作り、HTTP（NewMux）と worker（Supervise）へ渡し、ctx が取り消されるまで待ち受けて graceful shutdown する。
func run(ctx context.Context) error {
	cfg, err := loadConfig()
	if err != nil {
		return err
	}
	logger := applog.New(os.Stdout, slog.LevelInfo)
	slog.SetDefault(logger) // ライブラリが slog.Default() で出す行も同じ handler へ

	pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return fmt.Errorf("接続プールの作成: %w", err)
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		return fmt.Errorf("データベースへの接続確認: %w", err)
	}

	// HTTP。tx.Manager・リポジトリ・usecase・server・interceptor の並びは NewMux が内部で組む
	mux := handler.NewMux(handler.Deps{
		Pool:   pool,
		Logger: logger,
		Clock:  clock.System{},
		Auth:   handler.Auth(auth.NewVerifier(cfg.AuthSecret)),
	})
	protocols := new(http.Protocols)
	protocols.SetHTTP1(true)
	protocols.SetUnencryptedHTTP2(true)
	srv := &http.Server{
		Addr:              cfg.ListenAddr,
		Handler:           mux,
		Protocols:         protocols,
		ReadHeaderTimeout: readHeaderTimeout,
	}

	// worker。HTTP と同じ pool と logger を Deps で渡す。tx.Manager・リポジトリ・usecase・query service は NewHoldExpirer が内部で組む
	expirer := worker.NewHoldExpirer(worker.Deps{
		Pool:   pool,
		Logger: logger,
		Clock:  clock.System{},
		Every:  expireEvery,
	})
	workerCtx, stopWorker := context.WithCancel(ctx)
	defer stopWorker()
	var wg sync.WaitGroup
	wg.Go(func() { worker.Supervise(workerCtx, "hold_expirer", logger, expirer.Run) })

	serveErr := make(chan error, 1)
	go func() { serveErr <- srv.ListenAndServe() }()
	select {
	case err := <-serveErr:
		stopWorker()
		wg.Wait()
		return fmt.Errorf("サーバーの待ち受け: %w", err)
	case <-ctx.Done():
	}
	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	err = srv.Shutdown(shutdownCtx)
	wg.Wait() // Supervise は ctx の終了で返る。worker が止まってから pool を閉じる
	if err != nil {
		return fmt.Errorf("サーバーの停止: %w", err)
	}
	return nil
}
```

`worker.NewHoldExpirer` は `handler.NewMux` と同じ composition root で、`Deps.Pool` から `tx.NewManager`・`rdb.NewReservationRepository()`・`usecase.NewExpireReservation`・`query.NewDueHoldQuery(pool)`（`worker.DueHoldReader` の実物。期限が到来した仮押さえの予約番号を読む query service）を組む（[boundaries.md](boundaries.md) §4）。`run` はどちらの境界にも、環境で変わるもの（pool・logger・時計・周期）だけを渡す。

| 規則 | 理由 |
|---|---|
| logger は `run` が 1 つ作り、`handler.Deps.Logger` と `worker.Deps.Logger` に同じものを渡す | 境界が 2 つ（HTTP と worker）でも handler は 1 つ。`request_id` の付き方も秘匿の安全網も同じになる |
| `LISTEN_ADDR` は環境変数から読み、欠けていれば起動しない | `":8080"` を既定にすると、設定の欠けが「別のポートで待った」として現れる。既定へ倒さない |
| `NewMux` が interceptor の並びを、`NewHoldExpirer` が worker の依存を持つ。`run` は `Deps` を作るだけで、tx・リポジトリ・usecase を組まない | テストも同じ `NewMux` / `NewHoldExpirer` を呼ぶ。配線が 1 か所なら、テストと本番で `Logging` の位置や worker の依存が違うことが無い |
| worker は `sync.WaitGroup.Go` で `Supervise` を起動し、`run` が返る前に必ず `wg.Wait` する | `go` で投げ放すと、`run` が返って `pool.Close` した後に worker が DB を触る。`Supervise` は ctx の終了で返るので、待ち受けの失敗で返るときは `stopWorker` で止めてから待つ |
| `Shutdown` には取り消し済みの `ctx` ではなく別の ctx（timeout 付き）を渡す | 取り消し済みの ctx を渡すと即座に諦め、処理中の要求が切れる |

Connect を通らない HTTP エンドポイント（ヘルスチェック・Webhook 受信）は、同じ役割の `func(http.Handler) http.Handler` を 1 つ置き、ステータスコードと `duration_ms` を 1 行で記録する。役割は §2 と同じで、翻訳先が `connect.Code` から HTTP ステータスに変わるだけである。

## 4. worker の supervisor

常駐処理は `worker.Supervise(ctx, name, logger, fn)` で起動する。panic・予期せぬ終了・再起動を記録するのは supervisor だけで、`fn` の中は usecase と同じく「返すなら書かない」。

```go
package worker

import (
	"context"
	"fmt"
	"log/slog"
	"runtime/debug"
	"time"
)

const (
	minBackoff   = time.Second
	maxBackoff   = time.Minute
	resetRuntime = time.Minute // これ以上続けて動けたら backoff を初期値へ戻す
)

// Supervise は ctx が終わるまで fn を再起動しながら動かす。ctx の終了では何も記録しない。
func Supervise(ctx context.Context, name string, logger *slog.Logger, fn func(context.Context) error) {
	worker := slog.String("worker", name)
	backoff := minBackoff
	for ctx.Err() == nil {
		started := time.Now()
		err := runOnce(ctx, worker, logger, fn)
		if ctx.Err() != nil {
			return // 正常終了。記録しない
		}
		if time.Since(started) >= resetRuntime {
			backoff = minBackoff
		}
		logger.LogAttrs(ctx, slog.LevelError, "常駐 worker が予期せず終了したため再起動する",
			worker,
			slog.Duration("backoff", backoff),
			slog.Any("err", err),
		)
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		backoff = min(backoff*2, maxBackoff)
	}
}

// runOnce は fn を 1 回動かし、panic を stack 付きで記録して error にする。
func runOnce(ctx context.Context, worker slog.Attr, logger *slog.Logger, fn func(context.Context) error) (err error) {
	defer func() {
		p := recover()
		if p == nil {
			return
		}
		logger.LogAttrs(ctx, slog.LevelError, "常駐 worker が panic した",
			worker,
			slog.Any("panic", p),
			slog.String("stack", string(debug.Stack())),
		)
		err = fmt.Errorf("worker の panic: %v", p)
	}()
	return fn(ctx)
}
```

panic は「panic した」（stack）と「再起動する」（backoff）の 2 行になる。別の事象なので二重ログではない。

`fn` は [boundaries.md](boundaries.md) §4 の `HoldExpirer.Run` である。サイクル全体の失敗（期限到来の仮押さえの一覧が読めない）は `return err` で supervisor へ返し、1 件ごとの失敗と成功は `Run` の途中ログで出る。途中ログを持つ worker の `Run` は logger を DI で受ける。持たない worker には logger のフィールドを置かない。
