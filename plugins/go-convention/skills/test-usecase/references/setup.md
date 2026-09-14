# 実物で通す — DB・リポジトリ・tx・query service の用意

**usecase のテストは、本番と同じ部品を本番と同じコンストラクタで組み立てて `Execute` を呼ぶ。** 偽物に置き換えるのは、決められた ID を返す `IDGenerator` の 1 つだけである。時刻は usecase の入力 `At` で渡すので、差し替える `Clock` は無い。前提は永続化層のテスト支援 `rdbtest` のテーブルごとの投入関数で行に書き、テストの中で集約も SQL も組み立てない。

## 1. 何を実物にするか

| 部品 | 実物 | テストでの用意 | 偽物にしない理由 |
|---|---|---|---|
| DB | dockertest が起動した PostgreSQL | `main_test.go` の `TestMain` が 1 回起動し、`pool` を package 変数に持つ | in-memory の代替では DB 制約・tx・`pgtype` の挙動が変わり、tx 境界と協調の検証が嘘になる |
| リポジトリ | `rdb.NewReservationRepository()` | ループ本体で本番と同じコンストラクタを呼ぶ | 偽物は `Apply*` が呼ばれた回数しか言えない。実物なら「その結果、行がどうなったか」を言える |
| tx | `tx.NewManager(pool)` | 同上 | `func(ctx, fn) error { return fn(ctx) }` の素通しでは rollback が起きず、観点 4 が検証できない |
| query service / 読み取りポートの実装 | `query.NewActiveReservationQuery(pool)` / `query.NewNoShowQuery(pool)` 等 | 同上 | 偽物が返す事実は「usecase が何を読んだか」を言わない。実物なら前提の行から読んだことが言える |
| ドメイン（集約・VO） | そのまま | — | 置き換える理由が無い |
| 時刻 | 差し替え無し | 表の `in.At` の固定値 | usecase は `Clock` を持たず、境界が決めた時刻を `Input.At` で受ける。固定値を渡すので、期限・停止期間の判定が実行時刻に依存しない |
| ID | `usecasetest.FixedIDs(t, ids...)` | 表の `ids` の固定値 | **例外。** 生成された ID を行の突き合わせに使うため決定的にする。ID の生成規則（形式・一意性）は検証しない |

`IDGenerator` の固定実装は usecase のテスト支援 package `usecase/usecasetest` に置く。`*_test.go` のファイルスコープに型を置かない（テストの形の共通規則）。

```go
package usecasetest

import (
	"errors"
	"testing"

	"example.com/roomflow/reservation"
	"example.com/roomflow/usecase"
)

var errFixedIDsExhausted = errors.New("固定 ID が尽きた")

// FixedIDs は ids を先頭から順に返す IDGenerator。尽きたら error を返す。
// ID の生成規則はテストの対象ではないので、値は呼ぶ側が決める。
func FixedIDs(t *testing.T, ids ...string) usecase.IDGenerator {
	t.Helper()
	gen := &fixedIDs{}
	for _, s := range ids {
		id, err := reservation.NewID(s)
		if err != nil {
			t.Fatalf("固定 ID %q: %v", s, err)
		}
		gen.ids = append(gen.ids, id)
	}
	return gen
}

type fixedIDs struct {
	ids []reservation.ID
}

func (g *fixedIDs) NewReservationID() (reservation.ID, error) {
	if len(g.ids) == 0 {
		return reservation.ID{}, errFixedIDsExhausted
	}
	id := g.ids[0]
	g.ids = g.ids[1:]
	return id, nil
}
```

## 2. 使わないもの

| 使わない | 代わりに |
|---|---|
| リポジトリ・query service・読み取りポートの mock / stub / fake | 実物 ＋ `rdbtest.Seed{Table}` で前提の行を投入 |
| `tx.Manager` の素通し fake、`Run` を呼ばない経路 | 実物 `tx.NewManager(pool)` |
| SQLite / in-memory DB | dockertest の PostgreSQL |
| テスト本文の SQL（INSERT / SELECT の直書き） | `rdbtest.Seed{Table}` / `rdbtest.Read{Table}` |
| テスト本文での集約の組み立て（`RestoreTentative` / `Hold` を呼んで保存） | 前提は行で書く。集約はリポジトリが復元する |
| `time.Now()`・`time.Sleep`・実時間待ち | 表の `in.At` の固定値 |
| ID の正規表現・形式・連番の検証 | 検証しない。`ids` の固定値で行を指す |
| `.EXPECT()` の呼び出し回数・引数・順序 | DB の状態（`Read{Table}`）と返り値 |
| `t.Skip`（Docker が無いとき） | 失敗にする。環境を整える |

## 3. `TestMain` — package に 1 点

プロセス単位の共有資源（PostgreSQL の起動）は、usecase のテスト package の `main_test.go` にある `TestMain` 1 点で扱う。他のファイルに `TestMain` を置かない。`main_test.go` に置けるのは `pool`（または `*rdbtest.DB`）と `TestMain` と、起動・組み立てを支える関数だけで、他の package 変数を作らない。

```go
package usecase_test

import (
	"context"
	"log"
	"os"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/rdb/rdbtest"
)

// pool は TestMain が起動した実 PostgreSQL への接続。この package で唯一の package 変数。
var pool *pgxpool.Pool

// TestMain はプロセス単位の共有資源（dockertest の PostgreSQL）をこの 1 点で起動する。
// 起動の手順は rdbtest.Start が持ち、ここは Start → m.Run() → Close → os.Exit を書くだけ。
// 起動に失敗したら skip ではなく失敗にする。
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

| 項目 | 規則 |
|---|---|
| 起動 | `rdbtest.Start(ctx)` が dockertest でコンテナを起動し、スキーマを当て、`*rdbtest.DB` を返す。起動の手順（イメージ・待ち方・スキーマの当て方）は永続化層のテスト支援が持ち、usecase のテストは呼ぶだけ |
| 停止 | `m.Run()` の後に `db.Close(ctx)` を直接呼ぶ。`defer` は `os.Exit` で走らない |
| 失敗 | `log.Fatalf` で終える。`t.Skip` に相当する分岐を書かない。Docker が無い環境は失敗として現れる。`log.Fatalf` を許すのはこの `TestMain` だけで、テスト関数では `require` を使う |
| 並列 | 実 DB 1 つを package で共有するので、テスト関数にもサブテストにも `t.Parallel()` を書かない。ループ直前のコメントで理由を書く |
| 別 package | usecase ごとに package を分けるなら、その package ごとに `main_test.go` を 1 つ持つ。共有しない |

## 4. 各ケースの前提 — `Reset` → `Seed{Table}`

各ケースは自分の世界を組み立てる。ループ本体の先頭で全テーブルを空にし、表の `seed{Table}` を投入する。

```go
			ctx := t.Context()
			rdbtest.Reset(ctx, t, pool)
			rdbtest.SeedReservations(ctx, t, pool, tt.seedReservations)
			rdbtest.SeedTentativeHoldDeadlines(ctx, t, pool, tt.seedDeadlines)
			rdbtest.SeedReservationBaseEvents(ctx, t, pool, tt.seedBaseEvents)
```

| 規則 | 理由 |
|---|---|
| `Reset` はケースの先頭。`t.Cleanup` で消さない | 前のケースが何を残しても次のケースが自分で空にする。失敗したケースの行が残り、原因を DB で見られる |
| 前提は sqlc の行の型（`sqlcgen.Reservation` 等）で書く | 表を縦に読めば前提が分かる。集約を組み立てて保存すると、前提が関数の中に隠れ、保存の経路もテスト対象に混ざる |
| 観点が読むテーブルだけを投入する | 協調のケースなら読まれる側の行、呼び分けのケースなら復元に要る行。8 テーブル全部を毎ケース書かない |
| 投入しないテーブルの `seed` フィールドは書かない（nil） | `Seed*` は nil で何もしない。表に空スライスを並べない |
| 復元に要る従属行を忘れない | 仮押さえ予約を前提にするなら `tentative_hold_deadlines` も要る。無いと `FindByID` がデータ破損として error を返す |

`rdbtest` に求めること（無ければ永続化層のテスト支援へ返す。テスト本文で代用しない）:

| 関数 | 契約 |
|---|---|
| `Start(ctx) (*DB, error)` / `(*DB).Pool() *pgxpool.Pool` / `(*DB).Close(ctx) error` | 起動・接続・停止（dockertest の起動はこの 1 点） |
| `Reset(ctx, t, pool)` | 資料の全テーブルを空にし、identity 列を 1 に戻す |
| `Seed{Table}(ctx, t, pool, rows []sqlcgen.{Row})` | 行をそのまま投入する。`id` を明示した行を入れたら identity をその最大値まで進める（続く INSERT が衝突しない）。nil なら何もしない |
| `Read{Table}(ctx, t, pool) []sqlcgen.{Row}` | 全行を主キー順で返す。時刻は UTC に正規化する。行が無ければ nil を返す（`want{Table}` を書かないケースと一致する） |

identity 列（イベント表の `id`）は `Reset` で 1 に戻るので、`want{Table}` に投入順で決まる値を書ける。

## 5. DI の組み立て — 本番と同じコンストラクタ

ループ本体で、本番の組み立て（`main` の `run`）と同じコンストラクタを同じ順で呼ぶ。テスト専用のコンストラクタ・Option を作らない。

```go
			sut := usecase.NewConfirmReservation(tx.NewManager(pool), rdb.NewReservationRepository())
```

```go
			sut := usecase.NewHoldReservation(
				tx.NewManager(pool),
				rdb.NewReservationRepository(),
				query.NewActiveReservationQuery(pool),
				query.NewNoShowQuery(pool),
				usecasetest.FixedIDs(t, tt.ids...),
			)
```

| 規則 | 理由 |
|---|---|
| ケースごとに組み立てる（ループ本体の中） | `FixedIDs` はケースの `ids` を持つ。表の外で 1 回組むと、ケースごとの固定値が渡せない |
| `setup func(t) fixture` を使わない | 全ケースで同じ組み立てなので、フィールドではなくループ本体のコードである（テストの形の共通規則） |
| リポジトリのコンストラクタに `pool` を渡さない | リポジトリは ctx の tx に乗る。`pool` を渡す形になっていたら、それは usecase ではなく永続化層の実装の問題 |

## 6. 観測 — `Read{Table}` で観点のテーブルだけ

`Execute` の後、`pool`（tx の外）で読む。commit されていない行は見えないので、見えた行は commit の証拠になる。

```go
			// 観点で見るテーブルだけを読む。全テーブルの突き合わせは永続化層のテストの責務。
			assert.Equal(t, tt.wantReservations, rdbtest.ReadReservations(ctx, t, pool))
			assert.Equal(t, tt.wantConfirmedEvents, rdbtest.ReadReservationConfirmedEvents(ctx, t, pool))
```

| 規則 | 理由 |
|---|---|
| 読むテーブルはテスト関数で固定し、全ケースで同じ | ケースごとに読むテーブルを変えると、`want{Table}` を書かなかったのが「変化なし」なのか「見ていない」なのか読めない |
| `wantErr` のケースでも読む | 「拒まれて何も書かれない」が観点 1・4・5 の検証そのもの |
| 行の全カラムで `assert.Equal` する。列を選んで比べない | 行の型をそのまま比べれば、書き方が 1 つで済む。全カラムを見るのは「全テーブル」を見るのとは別で、読むテーブルを絞ることで薄さを保つ |
| イベント表の `id` / `base_event_id` は `Reset` 後の投入順で決まる値を書く | §4 の identity の契約 |
