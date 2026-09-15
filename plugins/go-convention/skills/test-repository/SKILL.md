---
name: go-convention-internal-test-repository
description: 永続化層（集約のリポジトリと query service）のテストを、dockertest で起動した実 PostgreSQL の上で書く・直す。リポジトリはデータモデル資料の BDD を「Before を投入 → 復元 → 実物の集約の操作 → 保存 → 資料の全テーブルを全行で突き合わせ」で写し、DB 制約違反の翻訳・楽観ロック競合・同時実行・NotFound を確かめる。query service は「Before を投入 → 読み取り → DTO を突き合わせ」で書く。「リポジトリのテストを書いて」「Apply{Event} のテストを足して」「query service のテストを書いて」「データモデル資料の BDD をテストにして」と言われたときに使う。集約・値オブジェクトの規則のテスト、usecase の tx 境界と協調のテスト、handler のテスト、リポジトリの実装そのものは対象外として、それぞれの規約へ返す。
---

# test-repository

これは、**永続化層のテストを、実 DB の上で「資料の Before から After へ行がどう変わるか」を全テーブルの全行で確かめる形に揃える規約**である。リポジトリのテストは復元 → 実物の集約の操作 → 保存で駆動し、query service のテストは Before を投入 → 読み取り → DTO の突き合わせで駆動する。

これは、**業務ルールのテストではない**（集約と値オブジェクトが拒む条件はドメインのテストが実 DB 無しで確かめる。集約が拒むシナリオはここに書かず、末尾コメントに理由を残す）。**usecase のテストでもない**（tx 境界・複数集約の協調・入力の解決は usecase のテストの関心）。**テストの形の共通規則でもない**（表の形・`id` / `name` / `description`・`want*` と `wantErr` は共通規則をそのまま使い、ここではこの層で決まる分だけを足す）。**リポジトリの実装規約でもない**（marshaller・sqlc・tx の乗り方は実装の規約が決め、ここでは公開メソッドを通して観測する）。

前提: Go 1.27・PostgreSQL・`github.com/jackc/pgx/v5`・`github.com/sqlc-dev/sqlc`（`sql_package: "pgx/v5"`）・`github.com/ory/dockertest/v4`・`github.com/stretchr/testify`・Docker daemon。入力はデータモデル資料（テーブル定義・「シナリオと記録の対応」・BDD の Before/After の表）、ドメインの実装（集約・`Restore*`・`As*`・sentinel）、リポジトリと query service の実装。例の題材は貸会議室予約 RoomFlow（module `example.com/roomflow`）で、ディレクトリ構成は上位の開発規約が決めるため、例は import path を短くするために平らにしている。

## 規約

| # | 柱 | 一言で | 正本 |
|---|---|---|---|
| 1 | 何をテストするか | 資料の BDD ごとの状態変化を全テーブル全行で（絶対規則）。復元と保存の往復、DB 制約違反の翻訳、楽観ロック競合、同時実行、NotFound。集約が拒むシナリオ・業務ルール・SQL の文言・marshaller 単体・ログは書かない | [what-to-test.md](references/what-to-test.md) |
| 2 | 実 DB | dockertest の起動は `rdbtest.Start` の 1 点。`main_test.go` の `TestMain` が `Start` → `m.Run()` → `Close` → `os.Exit` を書き、package 変数 `pool` を共有。起動失敗はテスト失敗。直列 | [dockertest-and-testmain.md](references/dockertest-and-testmain.md) |
| 3 | rdbtest | `rdb/rdbtest` に `Start` / `Reset` / `Run` / テーブルごとの `Seed{Table}` / `Read{Table}`。行型は sqlc の生成型、query は `rdb/query/rdbtest.sql`。テスト本文に SQL を書かない | [rdbtest.md](references/rdbtest.md) |
| 4 | テーブルの形 | `seed{Table}` × 全テーブル、When の引数、`wantErr`、`want{Table}` × 全テーブル。書かないテーブルは空と一致。同時実行は When をスライスにして 2 本並走 | [table-shape.md](references/table-shape.md) |
| 5 | query service | Before を投入 → 読み取り → DTO を `assert.Equal`。フィルタ・ページング・NULL・空の 4 観点。全テーブルの突き合わせは要らない | [query-service-test.md](references/query-service-test.md) |

完全な例は [table-shape.md](references/table-shape.md) §5 と [query-service-test.md](references/query-service-test.md) §3。**書き始める前に一度読み、この形を写す。**

## 手順

1. **資料と対象を揃える。** データモデル資料の「シナリオと記録の対応」と BDD の Before/After、リポジトリ（または query service）の公開メソッドを並べる。完了条件: 資料の全テーブルが列挙され、テーブルごとに `sqlcgen` の行型が 1 つ対応している
2. **`rdbtest` と `main_test.go` を用意する。** 無ければ [dockertest-and-testmain.md](references/dockertest-and-testmain.md) §1（`Start`）・§2（`main_test.go`）と [rdbtest.md](references/rdbtest.md) §3・§4 を写し、`sqlc generate` で `Read*` を生成する。完了条件: `go vet ./...` が通り、`rdbtest` に `Start` と資料の全テーブル分の `Seed{Table}` / `Read{Table}` がある
3. **BDD を割り振る。** 資料の BDD を [what-to-test.md](references/what-to-test.md) §5 の規則でメソッドのテスト関数へ割り振り、集約が拒むものは末尾コメントの候補にする。完了条件: 資料の全 ID が「どの関数に置く」か「書かない理由」のどちらかを持つ
4. **表を書く。** 資料の順に `id`（資料の ID）/ `name`（見出し文）/ `description`（gherkin ブロックの転記）、`seed{Table}` × 全テーブル（Before）、When の引数、`wantErr`、`want{Table}` × 全テーブル（After）。資料に無いケース（楽観ロック競合・復元・NotFound）を生成した id でその後ろに足す。完了条件: `description` の各行からフィールドの値が説明でき、全ケースが資料の全テーブル分の `want{Table}`（0 行は書かない）を持つ
5. **ループ本体を書く。** `Reset` → 全 `Seed` → `rdbtest.Run` の中で復元 → 絞り込み → 実物の操作 → 保存 → error の検証 → 全 `Read` → 全 `assert.Equal`。When が 2 件以上のケースがあれば [table-shape.md](references/table-shape.md) §4 の並走の形にする。完了条件: 全テーブルの `Read` と `assert.Equal` が error の分岐の外に 1 回ずつあり、`t.Parallel()` が無い
6. **末尾コメントを書く。** 資料にあるが書かない BDD を `// テストしない BDD:` に続けて ID と理由で列挙する。完了条件: 資料の全 ID が `id:` か末尾コメントのどちらか一方に現れる
7. **機械検査を通す。** テストの形の共通規則の機械検査を通した上で、次を実行する。`CLAUDE_PLUGIN_ROOT` は Claude Code が展開する。Codex では、この `SKILL.md` があるディレクトリの 2 つ上（plugin root）の絶対パスを入れる
   ```bash
   go vet ./...
   go test -count=1 ./rdb/ ./query/
   go test -count=1 -run 'TestReservationRepository_ApplyHeld/BDD-005_' ./rdb/   # 足したケースを 1 つずつ単独で
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/test-repository/scripts/check-bdd-coverage.py" <データモデル資料.md> <テストのあるディレクトリ>
   ```
8. **報告する。** 「報告」の項目を返す

## 停止条件

- データモデル資料が無い、または BDD に Before/After の表が無い → 表の `seed` / `want` を作れない。資料の作成へ返す
- 資料に登場するテーブルに `sqlcgen` の行型が無い（DDL に無い・sqlc の `schema` に入っていない） → 全テーブルの突き合わせができない。DDL とリポジトリの実装へ返す
- 資料の不変条件（重なり禁止・一意）が DDL の名前付き制約に無く、拒否を DB で再現できない → 書かない。データモデル資料とリポジトリの実装へ返す
- 資料の BDD の When が集約の操作に写せない（複数集約にまたがる・別の行為者の操作が混ざる） → 書かない。usecase のテストへ返し、末尾コメントに理由を書く
- リポジトリが `*pgxpool.Pool` を持ち `rdbtest.Run` の外で動く、または query service が書き込む → テストではなく実装の規約違反。実装の規約へ返す
- Docker daemon に接続できない → 起動失敗として落とす。`t.Skip` で通さない

## 機械検査で言えること

| 検査 | 通ったら言えること |
|---|---|
| `go vet` / コンパイル | 形の違反は見つからなかった |
| `go test -count=1 ./rdb/ ./query/` | 実 PostgreSQL の上で全ケースが通った |
| `go test -run 'TestX/BDD-001_'` が通る | そのケースは単独で通る（`Reset` が前提を作っている） |
| `check-bdd-coverage.py` | 次の 4 つの述語が成り立った。1. 資料に `### [BDD-NNN] 見出し` の形の見出しが 1 つ以上ある 2. 資料の各 BDD ID が、ディレクトリの `*_test.go` の `id:` の値か、`// テストしない BDD:` に続く `// BDD-NNN 理由` のどちらか一方に現れる（両方には現れない） 3. `id:` の値のうち `BDD-` で始まるものは、資料の見出しにある 4. `// テストしない BDD:` の列挙は 1 ファイルに 1 つで、ファイルの最後にあり、各行は `// BDD-NNN 理由` の形で理由が空でない。書かない理由が正しいとは言えない |

「全テーブルを突き合わせている」「Before/After が資料と一致している」「集約が拒むシナリオを書いていない」は、この検査では言えない。下のチェックリストを人が読む。

## チェックリスト（機械で言えないことだけ）

- [ ] 全ケースが資料に登場する全テーブル（実装が置く資料に無いテーブルを含む）の `Read{Table}` と `assert.Equal` を持ち、1 テーブルも省いていない。拒まれるケースの `want{Table}` は `seed{Table}` と同じ行で、空にしていない
- [ ] 保存する集約（イベント）は `FindByID` で復元した実物の操作（生成なら `Hold`）から得ていて、`Restore*` やイベントの組み立てで作っていない
- [ ] 集約が拒むシナリオ（期限・本人・資格・状態違い）を書いていない。書かなかった資料の BDD が末尾コメントに理由付きで列挙されている
- [ ] DB 制約で拒まれるケースの `wantErr` がドメインの sentinel（`reservation.ErrOverlappingSlot`）、競合が `rdb.ErrConflict`、無い集約が `rdb.ErrNotFound` になっている
- [ ] 同時実行のケースは When が 2 件で、先頭が先に成立し、最後が `wantErr` を受ける。goroutine の中で `require` を呼んでいない
- [ ] `seed{Table}` / `want{Table}` の値が資料の Before/After の表と一致し、時刻は UTC、identity の `id` は `Reset` 後の採番と一致している
- [ ] `TestMain` は `main_test.go` に 1 つだけで、`rdbtest.Start` → `m.Run()` → `Close` → `os.Exit` だけを書き、`t.Skip` が無い。`main_test.go` にあるのは `pool`（または `*rdbtest.DB`）・`TestMain`・起動を支える関数だけ。`t.Parallel()` が無く、ループ直前のコメントで共有 DB を名指ししている
- [ ] テスト本文と `rdbtest` に SQL 文が無い（`rdb/query/rdbtest.sql` だけ）。`setup` フィールドが無い
- [ ] query service のテストがフィルタ・ページング・NULL・空のうち対象にある観点を全部持ち、集約を復元していない

## 報告

- 対象（リポジトリ / query service）とテスト関数名、資料の全テーブルの一覧
- ケース数と内訳: 資料にあるケース（ID と置いた関数）/ 資料に無いケース（生成した id と観点: 競合・復元・NotFound・フィルタ等）/ テストしない BDD（ID と理由）
- 同時実行のケースと、先頭が先に成立する根拠（排他制約・行ロック）
- 機械検査の結果（`go vet` / `go test` / 単独実行 / `check-bdd-coverage.py`）と、実 DB の起動にかかった時間
- 資料・DDL・実装と食い違った点（列の有無、制約名、識別子の写し方）と、停止条件で返した論点
