# 組み立てと起動

**`main` は `run(ctx) error` を呼んで `os.Exit` するだけ。`run` は環境で変わるもの（接続プール・logger・時計・認証）を `handler.Deps` に詰めて `handler.NewMux` を呼び、tx・リポジトリ・query service・usecase・server・interceptor 列の配線は `NewMux` が内側（DB）から外側（HTTP）へ順に組み立てる。** 設定は環境変数から読み、欠けていれば起動しない。配線と interceptor の並びは `NewMux` の 1 か所に閉じ、`run` とテストが同じ関数を呼ぶ。

## 1. `main`

`cmd/roomflow/main.go`:

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
```

| 規則 | 理由 |
|---|---|
| `main` は `run` を呼ぶだけ。`defer` を置かない | `os.Exit` は `defer` を実行しない。後始末はすべて `run` の中の `defer` に置く |
| `signal.NotifyContext` で ctx を作り、`SIGINT` / `SIGTERM` で取り消す | 停止の合図が ctx の取り消しになり、`run` は ctx だけを見て graceful shutdown に入れる |
| `run` の error は `os.Stderr` に出して終了コード 1 | logger は `run` の中で作る。作る前の失敗（設定の欠け）も同じ経路で見える |

## 2. `run`

`cmd/roomflow/run.go`:

```go
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/applog"
	"example.com/roomflow/auth"
	"example.com/roomflow/clock"
	"example.com/roomflow/handler"
)

const (
	readHeaderTimeout = 10 * time.Second
	shutdownTimeout   = 10 * time.Second
)

type config struct {
	DatabaseURL string // DATABASE_URL。pgx の接続文字列
	ListenAddr  string // LISTEN_ADDR。":8080" のような待ち受けアドレス
	AuthSecret  string // AUTH_SECRET。Verifier の鍵
}

// loadConfig は環境変数を読む。欠けていれば error で、既定値へ倒さない。
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

func requireEnv(name string) (string, error) {
	v := os.Getenv(name)
	if v == "" {
		return "", fmt.Errorf("環境変数 %s が無い", name)
	}
	return v, nil
}

// run は環境で変わるものを Deps に詰めて NewMux を呼び、ctx が取り消されるまで待ち受け、graceful shutdown して返る。配線は NewMux にある。
func run(ctx context.Context) error {
	cfg, err := loadConfig()
	if err != nil {
		return err
	}
	logger := applog.New(os.Stdout, slog.LevelInfo)
	slog.SetDefault(logger) // ライブラリが slog.Default() で出す行も同じ handler へ

	// 1. DB
	pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return fmt.Errorf("接続プールの作成: %w", err)
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		return fmt.Errorf("データベースへの接続確認: %w", err)
	}

	// 2. 環境で変わるものだけを Deps に詰める。tx・リポジトリ・query service・usecase・server は NewMux が組む
	mux := handler.NewMux(handler.Deps{
		Pool:   pool,
		Logger: logger,
		Clock:  clock.System{},
		Auth:   handler.Auth(auth.NewVerifier(cfg.AuthSecret)),
	})

	// 3. HTTP。h2c（TLS 無しの HTTP/2）を http.Protocols で有効にする。golang.org/x/net/http2/h2c は要らない。TLS 終端は前段が担う
	protocols := new(http.Protocols)
	protocols.SetHTTP1(true)
	protocols.SetUnencryptedHTTP2(true)
	srv := &http.Server{
		Addr:              cfg.ListenAddr,
		Handler:           mux,
		Protocols:         protocols,
		ReadHeaderTimeout: readHeaderTimeout,
	}

	// 4. 待ち受けと停止
	serveErr := make(chan error, 1)
	go func() { serveErr <- srv.ListenAndServe() }()

	select {
	case err := <-serveErr:
		return fmt.Errorf("サーバーの待ち受け: %w", err)
	case <-ctx.Done():
	}
	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("サーバーの停止: %w", err)
	}
	return nil
}
```

| 規則 | 理由 |
|---|---|
| 設定は環境変数から読み、欠けていれば error。`":8080"` や `localhost` を既定にしない | 既定に倒すと、設定の欠けが「別の DB につながった」「別のポートで待った」として現れる。起動しないのが最も早い発見 |
| `run` が作るのは `Deps` の 4 つ（pool・logger・時計・認証）だけ。usecase やリポジトリを `run` で組まない | 環境で変わるものと変わらないものを分ける。配線が `NewMux` に閉じていれば、テストが同じ関数を呼んで本番と同じ配線を通る |
| 接続プールは 1 つ。`Deps.Pool` に渡し、`NewMux` が `tx.NewManager(pool)` と query service に渡す。リポジトリには渡さない | リポジトリは ctx の tx に乗る。pool を持つのは tx を張る側と、tx の外でも読む query service だけ |
| `pool.Ping` で起動時に接続を確かめる | 最初の要求で失敗するより、起動で失敗する方が早い |
| `defer pool.Close()` は `pgxpool.New` の直後 | `Shutdown` の後に閉じる順（`defer` は逆順）になる。処理中の要求が接続を失わない |
| `ListenAndServe` は goroutine で呼び、`select` で終了と ctx の取り消しを待つ | `ListenAndServe` は返らないので、ctx を見るには別 goroutine が要る。`ErrServerClosed` も `serveErr` に入るが、`Shutdown` 後は読まない |
| `Shutdown` に別の ctx（`context.Background()` ＋ timeout）を渡す | 取り消し済みの `ctx` を渡すと `Shutdown` が即座に諦め、処理中の要求が切れる |
| h2c は `http.Protocols` で有効にする | Go 1.24 以降の `net/http` が TLS 無しの HTTP/2 を持つ。`golang.org/x/net` の `h2c` を足さない |
| `slog.SetDefault(logger)` は `run` で 1 回 | 自前のコードは logger を DI で受け、`slog.Default()` を使わない。`SetDefault` はライブラリの行を同じ handler に集めるため |
| `clock` / `auth` の実装は `run` が選び、`idgen` は `NewMux` が選ぶ | 時計と認証は環境で変わる（テストは固定時計と主体注入を渡す）。採番は環境で変わらないので `Deps` に出さず、`NewMux` が本番の生成器を作る |

`auth.NewVerifier` の形は認証方式が決める。`clock.System` は `Now() time.Time` で `time.Now()` を返す struct（`clock/system.go`）。`run` はそれらを呼ぶだけで、実装を持たない。

## 3. `handler.NewMux`（composition root）

`handler/mux.go`:

```go
package handler

import (
	"log/slog"
	"net/http"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/gen/roomflowv1/roomflowv1connect"
	"example.com/roomflow/idgen"
	"example.com/roomflow/query"
	"example.com/roomflow/rdb"
	"example.com/roomflow/tx"
	"example.com/roomflow/usecase"
)

// Deps は環境で変わるものだけ。run は本番の値を、テストは実 DB・固定時計・主体注入の interceptor を渡す。
type Deps struct {
	Pool   *pgxpool.Pool
	Logger *slog.Logger
	Clock  Clock               // 操作の時刻を決めるサーバーの時計。本番は clock.System{}
	Auth   connect.Interceptor // 主体を Scope に載せる interceptor。本番は Auth(verifier)
}

// NewMux は tx・リポジトリ・query service・usecase・server・interceptor 列を内側から外側へ組み立て、
// ReservationService を登録した mux を返す。配線はここにだけあり、run とテストが同じ関数を呼ぶ。
func NewMux(d Deps) *http.ServeMux {
	manager := tx.NewManager(d.Pool)
	repo := rdb.NewReservationRepository()
	server := NewReservationServer(
		usecase.NewConfirmReservation(manager, repo),
		usecase.NewHoldReservation(manager, repo, query.NewActiveReservationQuery(d.Pool), query.NewNoShowQuery(d.Pool), idgen.NewRandom()),
		d.Clock,
	)
	mux := http.NewServeMux()
	path, h := roomflowv1connect.NewReservationServiceHandler(
		server,
		connect.WithInterceptors(Logging(d.Logger), d.Auth), // 先頭が最外
	)
	mux.Handle(path, h)
	return mux
}
```

`idgen/random.go`。usecase の `IDGenerator` の実物で、標準の `uuid` package（Go 1.27）を使う。サードパーティの uuid を足さない。`uuid.New()` の名前と返り値は書く前に pkg.go.dev で確認する（この例は Go 1.27 のリリース時点の形で、版が違えば pkg.go.dev が正）:

```go
package idgen

import (
	"uuid"

	"example.com/roomflow/reservation"
)

// Random は予約番号をランダムな UUID で採番する。
type Random struct{}

func NewRandom() Random { return Random{} }

// NewReservationID は uuid.New() の文字列を予約番号にする。NewID が拒む値は作れないが、生成の条件は 1 か所（NewID）に置く。
func (Random) NewReservationID() (reservation.ID, error) {
	return reservation.NewID(uuid.New().String())
}
```

| 規則 | 理由 |
|---|---|
| `Deps` は `Pool` / `Logger` / `Clock` / `Auth` の 4 つ。usecase・リポジトリ・query service を引数にしない | 引数にした時点で差し替え可能になり、テストが偽物を渡せてしまう。差し替え点を「時計と認証」に閉じるには、他を引数から外す |
| 採番（`idgen.NewRandom()`）は `NewMux` の中で作る | 採番は環境で変わらない。テストは応答の識別子と反映した行の識別子を突き合わせる |
| `WithInterceptors` を呼ぶのは `NewMux` だけ | 並び（`Logging` が最外）が 1 か所に決まる。テストが別の並びで組んで本番と違う挙動になることが無い |
| `Clock` と認証の interceptor は `Deps` で受ける | テストは固定時計と、主体を固定で注入する interceptor を渡す。`Logging`・server・usecase・リポジトリ・tx は本番と同じものが動く |
| `*http.ServeMux` を返す | `run` が Connect の外の endpoint（`GET /healthz`）を同じ mux に足せる。interceptor の chain を通らない endpoint はここに置く |
| service や usecase が増えたら `NewMux` に足す | 登録と配線の置き場を増やさない。`WithInterceptors(...)` は同じ並びを渡す |

## 4. 置き場

| path | 中身 |
|---|---|
| `cmd/roomflow/main.go` | `main` |
| `cmd/roomflow/run.go` | `config` / `loadConfig` / `requireEnv` / `run` |
| `handler/mux.go` | `Deps` と `NewMux` |
| `applog/` | `New(w, level)`。JSON handler に秘匿の安全網と ctx 属性を重ねた logger（ログの規約） |
| `auth/` | `Verifier` の実装（認証方式ごと） |
| `idgen/` | usecase の `IDGenerator` の実物（`Random`。標準の `uuid`） |
| `clock/` | handler の `Clock` の実物（`System`。`time.Now()`） |
