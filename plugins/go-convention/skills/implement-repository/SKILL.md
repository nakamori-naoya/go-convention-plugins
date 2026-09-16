---
name: implement-repository
description: ドメイン層に定義済みの集約の永続化ポート（Repository interface）を、PostgreSQL ＋ pgx/v5 ＋ sqlc で実装する。通常型（FindByID / Create / Update で状態を上書き）とイベント型（FindByID ＋ Apply{Event} でドメインイベントを追記し current 行へ反映）の 2 つの型、ctx の tx に乗る書き方、ドメインと行を往復させる marshaller、DB 制約違反・NotFound・楽観ロック競合の翻訳を定める。「このリポジトリを実装して」「集約の永続化を書いて」「Apply{Event} を実装して」「データモデル資料からリポジトリを起こして」と言われたときに使う。Repository interface の設計、トランザクションを張る側の書き方、一覧・件数・検索の読み取りモデル、DDL とマイグレーション、何をテストするかは対象外として、それぞれの規約へ返す。
---

# implement-repository

[工程順序の正本](playbook.yml)を最初に読み、同じagentが\`steps\`を宣言順に実行する。YAMLは工程順序を決め、各工程の判断内容と根拠はこの本文と参照資料を実読して評価する。失敗時は成功扱いせず停止して、完了工程、根拠、未決を残し、再開時は最初の未完了工程から続ける。

これは、**集約の永続化ポートの RDB 実装を、ドメインの値とテーブルの行の往復と、DB が拒んだ事実の翻訳だけで書く規約**である。

これは、**業務判断の置き場ではない**（何を許し何を拒むかは集約と VO が決める）。**トランザクションの持ち主ではない**（usecase の規約が張り、リポジトリは ctx の tx に乗る）。**読み取りモデルの生成器ではない**（一覧・件数・検索は行を DTO へ写す別物で、query service の規約が決める）。**interface の設計者でもない**（interface はドメインの規約が集約ごとに 1 つ定義済みで、ここでは実装だけを書く）。何をテストするかはテストの規約が決める。

前提: Go 1.27、PostgreSQL、`github.com/jackc/pgx/v5`（`pgxpool` / `pgtype` / `pgconn`）、`github.com/sqlc-dev/sqlc`（`sql_package: "pgx/v5"`）。入力はドメインの実装（集約・VO・`Repository` interface・sentinel）とデータモデル資料（テーブル定義と「シナリオと記録の対応」）。例の題材は貸会議室予約 RoomFlow（module `example.com/roomflow`）で、ディレクトリ構成は上位の開発規約が決めるため、例は import path を短くするために平らにしている。

## 規約

| # | 柱 | 一言で | 正本 |
|---|---|---|---|
| 1 | 責務 | 復元と永続化と翻訳だけ。業務判断・tx・ログ・Query 系・時刻と ID の採番をしない | [what-repository-is.md](references/what-repository-is.md) |
| 2 | 2 つの型 | データモデル資料にイベント系テーブルがあればイベント型（`Apply{Event}`、集約を受け取らない、楽観ロック）、無ければ通常型（`Create` / `Update`、版なし）。`FindByID` は和型を返し、状態指定取得は禁止 | [standard-and-event-sourced.md](references/standard-and-event-sourced.md) |
| 3 | marshaller | 同じ package の純粋関数。`{元}To{先}` 命名。行 → ドメインは `New*` と `Restore*` 経由。current 行が正本。NULL は `(T, bool)`。時刻は UTC | [marshaller.md](references/marshaller.md) |
| 4 | sqlc と tx | SQL は `rdb/query/{aggregate}.sql` だけ。`sqlcgen.New(tx)` を直接呼ぶ。tx は `tx.From(ctx)` から取り、無ければ `ErrNoTransaction` | [sqlc-and-tx.md](references/sqlc-and-tx.md) |
| 5 | エラー翻訳 | 制約違反 → ドメインの sentinel、`ErrNoRows` → `rdb.ErrNotFound`、楽観ロック 0 行と版の一意制約違反 → `rdb.ErrConflict`。書き込みの error は全部 `translateConstraint` に通す。文脈は `fmt.Errorf("予約 %s の保存: %w", id, err)` で 1 回 | [error-translation.md](references/error-translation.md) |

## 手順

1. **型を決める。** データモデル資料のテーブル一覧を読み、`{aggregate}_base_events` と詳細イベント表があればイベント型、無ければ通常型にする。ドメインの `Repository` interface がその型の形（`Apply{Event}` か `Create` / `Update` か）と一致していることを確かめる。完了条件: 集約 1 つに型が 1 つ決まり、実装するメソッドが interface のメソッドと 1:1 で列挙されている
2. **テーブル操作を表にする。** 資料の「シナリオと記録の対応」から、メソッドごとに各テーブルへの INSERT / UPDATE / DELETE を書き出す。イベント型は 1. current 行（初回は INSERT、以後は楽観ロック付き UPDATE）2. 従属行 3. 基底イベント 4. 詳細イベント の順に並べる。完了条件: 資料の表の各行が、どれか 1 つのメソッドの手順に写っている
3. **query を書き、生成する。** `rdb/query/{aggregate}.sql` に 2 の操作分の query を `{Get|Insert|Update|Delete}{Table}` で書き、`sqlc generate` で `rdb/sqlcgen` を更新する。楽観ロックの UPDATE は `:execrows`、基底イベントは `RETURNING id` の `:one`。完了条件: 生成が通り、メソッドが使う query がすべて 1 ファイルにあり、テスト用の query が混ざっていない
4. **marshaller を書く。** `rdb/{aggregate}_marshaller.go` に、ドメイン → Params（イベントまたは状態型ごと）と、行 → 集約（`status` で `Restore*` を選ぶ）を `{元}To{先}` で書く。`status` / `event_type` / `actor_code` の定数もここに置く。完了条件: 行 → ドメインが `New*` と `Restore*` だけを呼び、ドメイン → 行が getter だけを読み、`time.Now()` と `pgtype` の型がドメイン側に現れない
5. **メソッドを書く。** 各メソッドを `queries(ctx)` で始め、2 の順に生成メソッドを呼び、marshaller を通す。イベント型の UPDATE は 0 行で `ErrConflict`、通常型の UPDATE は 0 行で `ErrNotFound`。書き込み（INSERT / UPDATE / DELETE）の error は全部 `translateConstraint` に通し、文脈を 1 回足して返す。完了条件: メソッドに SQL 文・型スイッチ以外の分岐・`log/slog`・`Begin` / `Commit` が無い
6. **翻訳表を確かめる。** 資料の「常に守られること」のうち DB 制約で表すものが DDL で名前付き制約になっていて、`translateConstraint` の表でドメインの sentinel と 1:1 に対応している。イベント型なら基底イベントの `(集約 ID, version)` の名前付き一意制約が `ErrConflict` の行にある。完了条件: 翻訳表の制約名が DDL に実在し、対応する sentinel がドメインまたは `rdb` の package にある
7. **コンパイルを通す。** `go build ./... && go vet ./...`。完了条件: 両方が通る
8. **報告する。** 「報告」の項目を返す

## 停止条件

止まるのは、資料または規約の契約に反する要求、正本に無い決定が要る、利用者の許可が要る、toolが失敗した、のどれかに当たるときで、それ以外の判断の揺れでは止まらない。欠けているのが業務事実（操作・状態・拒む理由・資料が未決と明示した値）なら止まり、命名・分割・定義場所・並び・テストの置き場のような設計判断の揺れなら仮説を明示して進む。

- ドメインに `Repository` interface が無い、または interface の形が型と合わない（イベント型なのに `Update(ctx, agg)` がある、通常型なのに集約が版を持つ） → 実装せず、ドメインの規約へ返す
- データモデル資料が無い、または集約とテーブルの対応（「シナリオと記録の対応」）が読めない → 資料の作成へ返す
- interface に無いメソッド（状態指定取得・`Delete`・`Exists`・一覧・件数）を求められた → 足さず、読み取りモデルの関心かドメインの規約かを示して返す
- 資料の不変条件（重なり禁止・一意）が DDL の制約に無く、リポジトリで `SELECT` して判断しないと守れない → データモデル資料へ返す。リポジトリで判断しない
- usecase が tx を張っていない前提で「pool を持たせて動くようにして」と求められた → 従わず、usecase の規約へ返す

止まるときは、書いた範囲と書かなかった範囲を分け、返す先（資料、実装の規約、利用者）と必要な決定を報告に示す。

判断の揺れでは、その時点の根拠から最も筋の良い形を仮説として採り、仮説であることと採らなかった形を報告に明示して進む。

- 列と値オブジェクトの対応、marshallerの分割が資料から一意に決まらない: 資料の「シナリオと記録の対応」に最も近い形を採り、報告に仮説と示す。

## チェックリスト

- [ ] メソッドが interface と 1:1。状態指定取得・`Save` / `Update(ctx, agg)`（イベント型）・`Delete` / `Exists` / `List*` を足していない
- [ ] `FindByID` が和型を返し、current 行から復元している。イベント列を畳み込んでいない
- [ ] 全メソッドの先頭が `queries(ctx)`。`*pgxpool.Pool` を struct に持たず、`Begin` / `Commit` / `Rollback` を呼んでいない
- [ ] イベント型の `Apply*` が current 行の UPDATE → 従属行 → 基底イベント → 詳細イベントの順で、照合キーが `evt.Version().Value()-1`、`base_events.version` が `evt.Version().Value()`
- [ ] marshaller が `{元}To{先}` で、行 → ドメインは `New*` / `Restore*` だけ、ドメイン → 行は getter だけ。`time.Now()` が無い
- [ ] 行 → ドメインの時刻に `.UTC()` を通し、NULL 列を `(T, bool)` に写している。「起きたかどうか」を current 行の NULL 列で持たず、イベント表の有無で復元している
- [ ] `translateConstraint` の制約名が DDL の名前付き制約と一致し、翻訳先の sentinel が資料「拒むときの理由」の 1 行に対応している。表に無い制約違反を既定の sentinel へ丸めていない
- [ ] `ErrNoRows` → `ErrNotFound`、楽観ロック 0 行と版の一意制約違反 → `ErrConflict`、通常型 UPDATE 0 行 → `ErrNotFound` になっている。INSERT / UPDATE / DELETE の error を全部 `translateConstraint` に通している
- [ ] 文脈は 1 メソッド 1 回。文言に SQL 文・テーブル名・SQLSTATE が無い。`log/slog` を import していない

## 報告

- 集約名と選んだ型（通常型 / イベント型）と、その根拠になった資料のテーブル
- 実装したメソッドと、各メソッドが触るテーブル操作の表（手順 2 の表）
- marshaller の一覧（関数名と方向）
- 翻訳表（制約名 → sentinel）と、翻訳しなかった制約
- 仮定したこと（資料に無いテーブル・列・getter・物理型）と、資料またはドメインの実装と食い違った点
- 資料の未決を仮の値で埋めた定数（題材では `actor_code` の `actorDeadlineKeeper` / `actorNoShowKeeper`。物理設計で値が決まるまでの仮の定数）
- 停止条件で返した論点
