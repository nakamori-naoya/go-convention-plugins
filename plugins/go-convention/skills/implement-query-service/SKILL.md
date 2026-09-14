---
name: implement-query-service
description: CQRS の読み取り側（query service）を PostgreSQL ＋ pgx/v5 ＋ sqlc で実装する。usecase 側が定義した読み取りポートを満たす型を `query` package に置き、一覧・件数・検索・ページング・ソート・フィルタ・JOIN を SQL で行い、テーブルの行を読み取りモデル（公開フィールドの DTO）へ純粋関数で写す。ドメイン（集約・VO）を経由せず、集約を復元せず、書き込まず、tx を張らない。「この一覧を実装して」「空き状況の query service を書いて」「読み取りモデルを作って」「件数とページングを付けて」と言われたときに使う。読み取りポート（interface）の設計、トランザクションを張る側の書き方、集約の永続化と復元、DTO から proto への変換、何をテストするかは対象外として、それぞれの規約へ返す。
---

# implement-query-service

これは、**読み取りポートの RDB 実装を、SQL で作った行を DTO へ写すことだけで書く規約**である。

これは、**集約の永続化と復元を書く規約ではない**（それは永続化ポートの実装の関心で、`FindByID` と `Apply*` / `Create` / `Update` はそちらが持つ）。**読み取りポートを設計する規約でもない**（interface は usecase 側が使う分だけ切る）。**トランザクションの持ち主でもない**（usecase の規約が張り、query service は ctx の tx があればそれに乗り、無ければ pool で読む）。**proto を組み立てる場所でもない**（DTO → proto は入口の規約が持つ）。何をテストするかはテストの規約が決める。

前提: Go 1.27、PostgreSQL、`github.com/jackc/pgx/v5`（`pgxpool` / `pgtype`）、`github.com/sqlc-dev/sqlc`（`sql_package: "pgx/v5"`）。入力は読み取りの要求（どの画面・API がどの項目を要るか）とデータモデル資料（テーブル定義）。例の題材は貸会議室予約 RoomFlow（module `example.com/roomflow`）で、ディレクトリ構成は上位の開発規約が決めるため、例は import path を短くするために平らにしている。

## 規約

| # | 柱 | 一言で | 正本 |
|---|---|---|---|
| 1 | 責務 | 行 → DTO だけ。ドメイン非経由・書き込み無し・業務判断無し・tx を張らない・既定値へ丸めない | [query-service.md](references/query-service.md) §1 |
| 2 | 置き場と依存 | 読み取りポートは usecase が定義し、`query` package の型が満たす。`query` は `reservation`・`rdb` を import せず、`rdb/sqlcgen` と `tx` だけ共有 | [query-service.md](references/query-service.md) §2 |
| 3 | 接続と sqlc | ctx に tx があればそれ、無ければ pool。SQL は `rdb/query/{name}_read.sql` に SELECT だけ、`:many` / `:one`、列は明示 | [query-service.md](references/query-service.md) §3–§5 |
| 4 | ページング・件数・フィルタ | すべて SQL。`limit` は 1 以上 `MaxPageLimit` 以下で範囲外は error、件数は別 query・別メソッド、親子の一覧は親に `LIMIT` | [query-service.md](references/query-service.md) §6–§7 |
| 5 | DTO と行 → DTO | 公開フィールドの struct、業務語、`time.Time`（UTC）、NULL は値と有無の対、空は nil、`{Row}To{DTO}` の純粋関数、複数行 → 1 DTO は `seen` で畳む | [dto.md](references/dto.md) |
| 6 | command と worker の材料 | 仮押さえの command が読む「重なる有効な予約の利用枠」（`ActiveSlot`。半開区間の条件を SQL に書く）と「無断不利用の時刻」（`[]time.Time`）、常駐 worker が読む「期限到来の仮押さえの予約番号」（`[]string`）も同じ形。判定（重なり・資格・期限の到来）と資料の数（30 日・3 回）は書かない | [query-service.md](references/query-service.md) §8 |

## 手順

1. **DTO を決める。** 読み取りの要求から、返す項目を業務語の公開フィールドに並べ、各フィールドの出所をデータモデル資料の列（または SQL の集計）に対応させる。NULL 許可列は値と有無の対、親子はスライスにする。完了条件: 全フィールドに出所の列（または集計式）が 1 つ書けていて、ドメインの型・`pgtype`・proto がフィールドに無い
2. **SQL を書き、生成する。** `rdb/query/{name}_read.sql` に `{List|Get|Count}{何}` の SELECT を書く。JOIN・`WHERE`・`ORDER BY`（末尾に主キー）・`LIMIT` / `OFFSET`・`count(*)` をここに置き、`sqlc generate` で `rdb/sqlcgen` を更新する。完了条件: 生成が通り、行型の列が DTO のフィールドと 1:1 で対応している（余る列も足りない列も無い）
3. **行 → DTO を書く。** `query/{name}_marshaller.go` に `{Row}To{DTO}` の純粋関数を書く。NULL 列は `(T, bool)` を返す関数で写し、時刻は `.UTC()`、sqlc の幅は DTO の型へ変換、複数行 → 1 DTO は `seen` で畳む。完了条件: 関数が引数以外を読まず、error を返さず、DTO に `pgtype` が無い
4. **query 型とメソッドを書く。** `*pgxpool.Pool` を持つ struct と `New{Name}Query(pool)`。各メソッドは、引数の形の検査 → `queries(ctx, q.pool)` → 生成メソッド 1 回 → 行 → DTO → 返す、の順で書き、`:one` の `pgx.ErrNoRows` は `query.ErrNotFound` に翻訳し、文脈を 1 回足す。完了条件: メソッドに SQL 文・`reservation` / `rdb` の import・`Begin` / `Commit`・引数検査以外の分岐・`log/slog` が無い
5. **ポートと突き合わせる。** usecase 側の読み取りポート interface とメソッドのシグネチャ（引数・返り値の DTO）が一致することを確かめる。ポートが無ければ、この skill の DTO とメソッドをポートの案として報告に載せ、usecase の規約へ渡す。完了条件: `go build ./...` が通り、DI の組み立てで代入できる
6. **コンパイルを通す。** `go build ./... && go vet ./...`。完了条件: 両方が通る
7. **報告する。** 「報告」の項目を返す

## 停止条件

- DTO の項目が、テーブルの列からも SQL の集計からも導けず、集約の操作や VO の判定（重なり・資格・期限の到来）を呼ばないと決まらない → 書かない。値を書き込み時に確定して列に持つかをデータモデル資料へ返す
- 集約（`reservation.Reservation`）を返す一覧、または一覧の結果を `Restore*` で復元することを求められた → 書かない。集約の取得は永続化ポートの `FindByID` の関心で、一覧で集約を返す interface は作らない
- 読み取りの途中で書く必要が出た（閲覧記録・最終アクセス日時・キャッシュの更新） → 書かない。書き込みは command の関心で、usecase の規約へ返す
- 未指定の `limit` / ソート列 / 日付を既定値で埋めることを求められた → 丸めない。呼び手（usecase）が明示する
- 呼び手からソート列や任意の条件式を受け取って SQL を組み立てることを求められた → 組み立てない。条件の組ごとに query を分ける
- データモデル資料が無い、または DTO に要る列が資料のどのテーブルにも無い → 資料の作成・改訂へ返す
- 引数に VO（`reservation.RoomCode`）を受け取ることを求められた → 受け取らない。ポートの引数は `string` / `time.Time` / `Page` で、VO から値を取り出すのは usecase

## チェックリスト

- [ ] `reservation`（ドメイン）と `rdb`（永続化）を import していない。`New*` / `Restore*` / リポジトリのメソッドを呼んでいない
- [ ] SQL は `rdb/query/{name}_read.sql` だけにあり、SELECT のみ（INSERT / UPDATE / DELETE / `FOR UPDATE` が無い）。列を明示している
- [ ] フィルタ・ソート・`LIMIT` / `OFFSET`・`count(*)` が SQL にあり、Go 側で並べ替え・絞り込み・数え上げをしていない
- [ ] `limit` の範囲外と `offset` の負が error。既定値へ丸めていない。日付の時刻部分を切り捨てていない。`time.Now()` を呼んでいない
- [ ] `queries(ctx, pool)` で tx があればそれ、無ければ pool。`Begin` / `Commit` / `Rollback` を呼んでいない。`Queries` を struct に持っていない
- [ ] 行 → DTO が `{Row}To{DTO}` の純粋関数で、NULL 列は `(T, bool)` → 値と有無の対、時刻は `.UTC()`、0 件は nil、sqlc の幅は DTO の型へ変換
- [ ] DTO は公開フィールドの struct でメソッドが無く、業務語の名前で、`pgtype` / proto / ドメインの型 / ポインタが無い
- [ ] `:one` の `pgx.ErrNoRows` を `query.ErrNotFound` に翻訳している。文脈は 1 メソッド 1 回で、文言に SQL 文・テーブル名が無い。`log/slog` を import していない
- [ ] 生成メソッドは 1 メソッド 1 回。件数は別メソッド。親子の一覧は親に `LIMIT` を掛けてから JOIN
- [ ] usecase 側の読み取りポートのシグネチャと一致している

## 報告

- query 型と実装したメソッド（シグネチャ）、対応する usecase 側のポート（無ければポートの案）
- SQL ファイルのパスと query 名、各 query の注釈（`:many` / `:one`）と、JOIN したテーブル
- DTO の一覧と、各フィールドの出所（テーブルの列または集計式）。値と有無の対にしたフィールド
- 行 → DTO 関数の一覧（名前と方向）と、`seen` で畳んだ親子
- 引数の検査と対応する sentinel、`ErrNotFound` に翻訳したメソッド
- 仮定したこと（資料に無い列・物理型・語彙）と、資料と食い違った点
- 停止条件で返した論点
