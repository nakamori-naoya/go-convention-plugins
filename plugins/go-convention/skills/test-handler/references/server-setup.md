# 起動と差し替え

**`run` と同じ組み立て関数に、実 DB・固定 `Clock`・主体注入 interceptor を渡して `httptest.NewServer` に載せ、生成クライアントで叩く。** 組み立てをテストが自分で書くと、本番の配線と食い違った server をテストすることになる。

## 1. 組み立て関数（実装側にあるもの）

`run` は組み立て関数 `NewMux` を 1 回呼ぶだけで、tx・リポジトリ・query service・usecase・server・interceptor 列の配線は関数の中にある（composition root）。テストも同じ関数を呼ぶ。環境で変わるのは `Deps` の 4 つだけである。

```go
package handler

import (
	"log/slog"
	"net/http"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/gen/roomflowv1/roomflowv1connect"
	"example.com/roomflow/idgen"
	query "example.com/roomflow/reservation/query"
	"example.com/roomflow/rdb"
	"example.com/roomflow/tx"
	"example.com/roomflow/usecase"
)

// Clock は server が要求の時刻（usecase の Input.At）を決めるための現在時刻。handler が定義する。
type Clock interface {
	Now() time.Time
}

// Deps は環境で変わるものだけ。run は本番の値を、テストは実 DB・固定時刻・主体注入を渡す。
type Deps struct {
	Pool   *pgxpool.Pool
	Logger *slog.Logger
	Clock  Clock               // Now() time.Time
	Auth   connect.Interceptor // 主体を ctx に載せる interceptor。本番は Auth(verifier)
}

// NewMux は tx・リポジトリ・query service・usecase・server・interceptor 列を組み立てる。配線はここにだけある。
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
		connect.WithInterceptors(Logging(d.Logger), d.Auth), // 先頭が最外。翻訳とログは最外、主体はその内側
	)
	mux.Handle(path, h)
	return mux
}
```

| 規則 | 理由 |
|---|---|
| 引数は `Pool` / `Logger` / `Clock` / `Auth` の 4 つ。usecase やリポジトリを引数にしない | 引数にした時点で差し替え可能になり、テストが偽物を渡せてしまう。差し替え点を「認可 1 つ」に閉じるには、他を引数から外す |
| ID の採番は関数の中で本番の生成器（`idgen.NewRandom()`。標準の `uuid`）を作る。テストから見えない | 採番は環境で変わらない。採番した値は表に書けないので、採番する RPC（仮押さえ）では応答の識別子と反映した行の識別子が同じであることをループ本体で突き合わせる（[table-shape.md](table-shape.md) §4） |
| `Clock` は引数。server が全 RPC の時刻（usecase の `Input.At`）を `Clock` から埋め、要求から時刻を受け取らない | 「今」が固定でなければ、確定の期限判定も仮押さえの期限（`now` の 15 分後）も期待値を表に書けない。本番は `time.Now` を返す実装を渡す。クライアント申告の時刻で期限を判定しない |
| handler は主体を ctx から読む（`reqctx.From(ctx)` の `Caller`） | 主体を載せる役が interceptor 1 つに閉じるから、その interceptor だけを差し替えれば認可の経路を変えずに主体を決められる |

この形になっていなければ、SKILL.md の停止条件で実装側へ返す。

## 2. `main_test.go`

`TestMain` はこのファイルの 1 つだけ。永続化層のテスト支援 `rdbtest.Start` で実 PostgreSQL を 1 回起動し、package 変数 `pool` に持つ。`newTestServer(t)` も同じファイルに置く。`main_test.go` に置けるのは `pool`（または `*rdbtest.DB`）・`now`・`TestMain`・起動と組み立てを支える関数だけで、他の `*_test.go` のファイルスコープには `Test*` 以外を置かない。

```go
package handler_test

import (
	"context"
	"log"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/gen/roomflowv1/roomflowv1connect"
	"example.com/roomflow/handler"
	"example.com/roomflow/handler/handlertest"
	"example.com/roomflow/rdb/rdbtest"
)

// pool はこの package の全テストが共有する実 PostgreSQL。TestMain が 1 回だけ起動する。
var pool *pgxpool.Pool

// now は server が決める時刻の固定値。確定の期限判定も仮押さえの期限（15 分後）も、この値から決まる。
var now = time.Date(2026, 9, 1, 9, 5, 0, 0, time.UTC)

// TestMain は rdbtest.Start → m.Run() → Close → os.Exit を書くだけ。起動の手順は rdbtest が持つ。
func TestMain(m *testing.M) {
	ctx := context.Background()
	db, err := rdbtest.Start(ctx)
	if err != nil {
		log.Fatalf("テスト用 PostgreSQL の起動: %v", err)
	}
	pool = db.Pool()

	code := m.Run()

	if err := db.Close(ctx); err != nil {
		log.Printf("テスト用 PostgreSQL の停止: %v", err)
	}
	os.Exit(code)
}

// newTestServer は run と同じ組み立て関数で server を作り、httptest で起動して生成クライアントを返す。
// 差し替えは Auth だけ。usecase・リポジトリ・tx・DB は本物を通る。
func newTestServer(t *testing.T) roomflowv1connect.ReservationServiceClient {
	t.Helper()
	mux := handler.NewMux(handler.Deps{
		Pool:   pool,
		Logger: slog.New(slog.DiscardHandler),
		Clock:  handlertest.FixedClock{At: now},
		Auth:   handlertest.CallerFromHeader(),
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return roomflowv1connect.NewReservationServiceClient(http.DefaultClient, srv.URL)
}
```

| 規則 | 理由 |
|---|---|
| `TestMain` は `main_test.go` の 1 点で、`rdbtest.Start` → `m.Run()` → `Close` → `os.Exit` だけ。起動の手順を書かない | dockertest の起動・待ち合わせ・スキーマ適用をテスト package ごとに書かない。永続化層・usecase・handler の 3 package が同じ起動を使う |
| 起動に失敗したら `log.Fatalf`。`log.Fatalf` を許すのは `TestMain` だけ | `TestMain` には `t` が無い。テスト関数では `require` を使う |
| `pool` は package 変数 | `TestMain` の結果をテスト関数へ渡す手段が他に無い。これが `Test*` 以外をファイルスコープに置く理由で、`main_test.go` に閉じる |
| `now` は固定。`time.Now()` をテストに書かない | 仮押さえの期限（`now` の 15 分後）が表に書ける。動く時刻では `want{Table}` の値が決まらない |
| logger は `slog.DiscardHandler` | ログは検証しない。出力があるとテストの出力に混ざり、失敗の行が読みにくい |
| `newTestServer` はテスト関数の先頭で 1 回呼ぶ。ケースごとに起動しない | 直列なので server は 1 つで足りる。`t.Cleanup(srv.Close)` がテスト関数の終わりに走る |
| 返すのはクライアント。`*httptest.Server` を返さない | テストが使うのはクライアントだけ。URL やハンドラに触る経路を渡さない |

## 3. 唯一の差し替え: 主体注入 interceptor

本番の認可 interceptor は Authorization ヘッダを検証して主体を ctx に載せる。テストは検証をせず、ヘッダの値をそのまま主体にする interceptor を**同じ位置に**挿す。テスト用の型は `handler/handlertest` package にだけ置く。ここに置かれた型の数が、差し替えの数である。

`handler/handlertest/caller_interceptor.go`:

```go
package handlertest

import (
	"context"
	"errors"
	"time"

	"connectrpc.com/connect"

	"example.com/roomflow/reqctx"
)

// CallerHeader はテストが主体を渡すヘッダ。本番の interceptor はこのヘッダを読まない。
const CallerHeader = "X-Test-Caller"

var (
	errNoCaller = errors.New("主体が指定されていない")
	errNoScope  = errors.New("リクエストの属性の入れ物が無い")
)

// CallerFromHeader は本番の認可 interceptor の代わりに挿す唯一の差し替え。
// 検証はせず、ヘッダの値をそのまま主体として ctx に載せる。無ければ Unauthenticated。
func CallerFromHeader() connect.UnaryInterceptorFunc {
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			caller := req.Header().Get(CallerHeader)
			if caller == "" {
				return nil, connect.NewError(connect.CodeUnauthenticated, errNoCaller)
			}
			s, ok := reqctx.From(ctx)
			if !ok {
				return nil, connect.NewError(connect.CodeInternal, errNoScope) // 最外の interceptor が入れ物を作っていない。組み立ての誤り
			}
			s.Caller = caller
			return next(ctx, req)
		}
	}
}

// FixedClock は常に At を返す。
type FixedClock struct{ At time.Time }

func (c FixedClock) Now() time.Time { return c.At }
```

| 規則 | 理由 |
|---|---|
| 差し替えるのは認可 interceptor だけ。検証器（`Verifier`）の偽物を渡す形にしない | 検証器を差し替えると本番の interceptor のコードは通るが、「本番と同じ経路」の利益より「差し替え点が増える」不利益が大きい。主体を決める役だけを持つ最小の型 1 つに閉じる |
| 主体は結果だけを返す。トークンの解釈・期限・失効を持たない | それらは認可 interceptor 自身のテストの関心で、ここには無い |
| ヘッダが無ければ `Unauthenticated` | 主体無しのケースが書ける。「無ければ既定の主体」にしない（フォールバック禁止） |
| 入れ物が無ければ `Internal` | 最外の interceptor より外に挿された誤りを黙って通さない |
| `handlertest` に置くのは `CallerFromHeader` と `FixedClock` だけ（`handler/handlertest/caller_interceptor.go` の 1 ファイル）。テーブルの投入・読み取り関数を置かない | 投入・読み取りは永続化層のテスト支援（`rdbtest`）の役。同じ関数を 2 か所に持たない |

## 4. 生成クライアントで叩く

```go
client := newTestServer(t)

req := connect.NewRequest(&roomflowv1.ConfirmReservationRequest{
	ReservationId: "R-20260901-0101",
})
req.Header().Set(handlertest.CallerHeader, "C-4102")
got, err := client.ConfirmReservation(t.Context(), req)
```

| 項目 | 使うもの | 理由 |
|---|---|---|
| クライアント | `roomflowv1connect.NewReservationServiceClient(http.DefaultClient, srv.URL)` | 生成コードが proto の直列化・URL・ヘッダを決める。手で `http.Post` を書くと本番のクライアントと違う形で叩くことになる |
| 主体 | `req.Header().Set(handlertest.CallerHeader, caller)`。`caller` が空なら設定しない | 主体無しのケースは「ヘッダが無い」で表す |
| Code | `connect.CodeOf(err)` | `*connect.Error` を包んでいても Code を返す。`err == nil` に対しては `CodeUnknown` を返すので、成功は `wantCode` の 0 で先に分岐する（[table-shape.md](table-shape.md) §3） |
| 文言 | `errors.AsType[*connect.Error](err)` の `Message()` | サーバが `connect.NewError(code, sentinel)` で作った文言がそのまま届く。包んだ文脈は届かない |
| 応答 | `got.Msg` の getter を射影 struct に写して `assert.Equal` | proto message を直接 `assert.Equal` すると内部フィールドで不一致になる |

## 5. 直列

`t.Parallel()` はテスト関数にもサブテストにも書かない。ループの直前に共有資源を名指しする。

```go
	// 同じ PostgreSQL（pool）を共有し、各ケースが Reset するため直列で走らせる。
	for _, tt := range tests {
```

各ケースは `rdbtest.Reset` で全テーブルを空にしてから前提を投入する。ケース間に依存は無く、どのケースも `-run 'TestX/<id>_'` で単独で通る。
