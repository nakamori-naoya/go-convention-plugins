# dockertest と TestMain

**実 DB は dockertest（`github.com/ory/dockertest/v4`）で起動した PostgreSQL 1 つを、package の `main_test.go` にある `TestMain` 1 点で起動し、package 変数 `pool *pgxpool.Pool` で全テストが共有する。** 起動のコード（コンテナの起動・接続の待ち合わせ・スキーマの適用・片付け）は `rdb/rdbtest` の `Start` にだけあり、`TestMain` は `Start` → `m.Run()` → `Close` → `os.Exit` を書くだけである。テスト関数ごとにコンテナを起動しない。起動できなければテストは失敗する（`t.Skip` を書かない）。

前提: Go 1.27、`github.com/ory/dockertest/v4`（v4.0.0 以降。`NewPool(ctx, "")` / `Run(ctx, image, opts...)` / `Retry(ctx, timeout, fn)` / `Close(ctx)` の形）、`github.com/jackc/pgx/v5/pgxpool`。Docker daemon が動いていること。

## 1. `rdbtest.Start` — 起動は 1 点

`rdb/rdbtest/start.go` に置く。`rdbtest` は dockertest に依存する（テスト支援 package で、本番コードは import しない）。実 DB を使う package（永続化層・usecase・handler）の `main_test.go` は全部この `Start` を呼び、起動の手順を自分で書かない。

```go
package rdbtest

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"path/filepath"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	dockertest "github.com/ory/dockertest/v4"

	"example.com/roomflow/rdb/schema"
)

// DB は Start が起動した実 PostgreSQL。Pool で接続を、Close で片付けを提供する。
// docker の型名（ClosablePool）と NewPool / Run / Retry / Close の形は dockertest v4 の pkg.go.dev で確認する。
type DB struct {
	docker dockertest.ClosablePool
	pool   *pgxpool.Pool
}

// Start は dockertest で PostgreSQL を起動し、接続が通るまで待ち、スキーマを当てて返す。
// 起動・接続・スキーマのどれかが失敗したら、起動したものを片付けて error を返す。
func Start(ctx context.Context) (*DB, error) {
	docker, err := dockertest.NewPool(ctx, "")
	if err != nil {
		return nil, fmt.Errorf("Docker に接続できない: %w", err)
	}
	// WithoutReuse: この package 専用のコンテナにする。go test ./... は package を並列に走らせるので、同じ DB を共有しない。
	container, err := docker.Run(ctx, "postgres",
		dockertest.WithTag("17"),
		dockertest.WithEnv([]string{"POSTGRES_USER=roomflow", "POSTGRES_PASSWORD=roomflow", "POSTGRES_DB=roomflow"}),
		dockertest.WithoutReuse(),
	)
	if err != nil {
		return nil, errors.Join(fmt.Errorf("PostgreSQL を起動できない: %w", err), docker.Close(ctx))
	}
	dsn := "postgres://roomflow:roomflow@" + container.GetHostPort("5432/tcp") + "/roomflow?sslmode=disable"
	// 起動直後は接続を拒むので、Ping が通るまで試す。時間切れは起動失敗として扱う。
	var pool *pgxpool.Pool
	err = docker.Retry(ctx, 2*time.Minute, func() error {
		p, err := pgxpool.New(ctx, dsn)
		if err != nil {
			return err
		}
		if err := p.Ping(ctx); err != nil {
			p.Close()
			return err
		}
		pool = p
		return nil
	})
	if err != nil {
		return nil, errors.Join(fmt.Errorf("PostgreSQL に接続できない: %w", err), docker.Close(ctx))
	}
	if err := applySchema(ctx, pool); err != nil {
		pool.Close()
		return nil, errors.Join(fmt.Errorf("スキーマを当てられない: %w", err), docker.Close(ctx))
	}
	return &DB{docker: docker, pool: pool}, nil
}

// Pool は起動した PostgreSQL への接続。
func (db *DB) Pool() *pgxpool.Pool { return db.pool }

// Close は接続を閉じ、コンテナを片付ける。
func (db *DB) Close(ctx context.Context) error {
	db.pool.Close()
	if err := db.docker.Close(ctx); err != nil {
		return fmt.Errorf("コンテナを片付けられない: %w", err)
	}
	return nil
}

// applySchema は rdb/schema の DDL をファイル名順に流す。マイグレーションの道具は上位の規約が決めるので、例は素朴に流す。
func applySchema(ctx context.Context, pool *pgxpool.Pool) error {
	entries, err := fs.ReadDir(schema.FS, ".")
	if err != nil {
		return err
	}
	for _, e := range entries {
		if e.IsDir() || filepath.Ext(e.Name()) != ".sql" {
			continue
		}
		ddl, err := fs.ReadFile(schema.FS, e.Name())
		if err != nil {
			return err
		}
		if _, err := pool.Exec(ctx, string(ddl)); err != nil {
			return fmt.Errorf("%s: %w", e.Name(), err)
		}
	}
	return nil
}
```

DDL の契約定義は `rdb/schema/*.sql` で、同じディレクトリの `schema.go` が `embed.FS` として公開する。`Start` を呼ぶ package の作業ディレクトリに依らず同じ DDL が当たる。

```go
// Package schema は rdb/schema/*.sql（DDL の契約定義）を埋め込んで公開する。sqlc も同じファイルを schema として読む。
package schema

import "embed"

//go:embed *.sql
var FS embed.FS
```

| 規則 | 理由 |
|---|---|
| 起動のコードは `rdbtest.Start` の 1 点。`main_test.go` に dockertest を書かない | 永続化層・usecase・handler の 3 package が同じ起動を使う。package ごとに写すと、待ち方や tag が package で食い違う |
| `dockertest.WithoutReuse()` で package 専用のコンテナにする | v4 は既定で `repository:tag` が同じコンテナを再利用する。`go test ./...` は package を並列に走らせるので、共有すると別 package の `Reset` が自分の Before を消す |
| 接続は `docker.Retry` で `Ping` が通るまで待つ。時間切れは起動失敗 | PostgreSQL は起動直後に接続を拒む。固定の `time.Sleep` は環境で足りたり足りなかったりする |
| 途中で失敗したら起動したものを片付け、片付けの error は `errors.Join` で足して返す | コンテナを残さない。片付けの失敗を `_ =` で捨てない |
| スキーマは `rdb/schema/*.sql` を `embed.FS` からファイル名順に流す。テストの中で DDL を書かない | DDL の契約定義は 1 か所。名前付き制約（`room_booking_claims_no_overlap`）がテストと本番で同じになる |
| PostgreSQL の版は本番と同じ tag を固定する（例は `17`）。`latest` にしない | 排他制約・`generated as identity` の挙動が版で変わりうる。動く版を固定する |
| `Close(ctx)` は `pool.Close()` → `docker.Close(ctx)` の順 | 接続を閉じてからコンテナを止める。逆だと接続の切断が error として上がる |

`applySchema` のようなマイグレーションの道具は上位の開発規約が決める。例は `fs.ReadDir` で素朴に流しているが、道具が決まっていればそれを `Start` から呼ぶ。

## 2. `main_test.go`

package `rdb` のテスト（`rdb_test`）に置く。query service の package（`query_test`）にも同じものを置く（中身は同じ）。

```go
package rdb_test

import (
	"context"
	"log"
	"os"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/rdb/rdbtest"
)

// pool は package の全テストが共有する実 PostgreSQL への接続。TestMain だけが代入する。
var pool *pgxpool.Pool

// TestMain は package に 1 つ。rdbtest.Start が起動した実 PostgreSQL の pool を共有し、終わったら片付ける。
// os.Exit は defer を走らせないので、片付けは m.Run() の後に直接呼ぶ。
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
```

| 規則 | 理由 |
|---|---|
| `TestMain` は package に 1 つ、`main_test.go` にだけ置く。他の `*_test.go` に `TestMain` も package 変数も置かない | プロセス単位の資源の置き場を 1 か所にする。テストの形の共通規則が `TestMain` を禁じ、実 DB を使う層の規約がこの 1 点だけを許す |
| `TestMain` の中身は `Start` → `m.Run()` → `Close` → `os.Exit` だけ。起動の手順を書かない | 起動手順の契約定義は `rdbtest.Start`（§1）。`main_test.go` に手順があると、package ごとに手順が分かれる |
| `pool` は `TestMain` だけが代入し、テスト関数は読むだけ | 接続を作り直すテストがあると、直列の前提（同じ DB を同じ接続で使う）が崩れる |
| 起動に失敗したら `log.Fatalf` で落とす。`t.Skip` を書かない | 起動失敗を Skip にすると、CI で DB のテストが 1 つも走らないまま緑になる |
| `log.Fatalf` を許すのは `TestMain` だけ。テスト関数・`rdbtest`・本番コードでは使わない | `TestMain` には `t` が無く、`os.Exit` 相当で終える手段がこれしか無い。それ以外は `require` か error を返す |
| `m.Run()` → `db.Close(ctx)` → `os.Exit(code)` の順に直接呼ぶ。`defer` を使わない | `os.Exit` は `defer` を走らせない。`defer` に書いた片付けはコンテナを残す |

`main_test.go` に置けるのは `pool`（または `*rdbtest.DB`）と `TestMain` と、起動・組み立てを支える関数だけで、ケースの組み立てを支える関数は置かない（それは `rdbtest` の関心。[rdbtest.md](rdbtest.md)）。

## 3. 直列

**同じ実 DB を全ケースが共有するので、`t.Parallel()` を書かない。** テスト関数の先頭にもサブテストの先頭にも書かず、ループの直前のコメントで共有資源を名指しする。

```go
	// 同じ実 DB（TestMain の pool）を全ケースが共有するため直列で走らせる（t.Parallel() を書かない）。
	for _, tt := range tests {
```

各ケースの先頭で `rdbtest.Reset` が全テーブルを空にする。ケースの独立はこの `Reset` が保証し、順序に意味を持たせない。`go test -shuffle=on` はテスト関数の順序を入れ替えるので、`Reset` 漏れがあればそこで落ちる。

## 4. 実行

```bash
go vet ./...
go test -count=1 ./rdb/ ./query/                       # 実 DB を起動する package だけ
go test -count=1 -run 'TestReservationRepository_ApplyHeld/BDD-005_' ./rdb/   # 1 ケースだけ
```

- `-count=1` でキャッシュを使わない。DB の状態はキャッシュの鍵に入らない
- Docker のソケットが既定の場所に無い環境（Docker Desktop・OrbStack・Colima）では `DOCKER_HOST` を設定してから走らせる。設定が無ければ起動失敗として落ちる
- コンテナの起動に数十秒かかる。package を細かく分けず、実 DB を使う package を `rdb` と `query` の 2 つに保つ
