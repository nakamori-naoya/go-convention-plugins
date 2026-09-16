---
name: test-handler
description: Connect-RPC の handler を、本番と同じ組み立てで `httptest.NewServer` に起動し、生成クライアントで公開 API として叩くテスト（API テスト）を書く・直す。proto と入力の変換、sentinel から `connect.Code` への翻訳と公開文言、認可（主体無し・他人）、成功後の永続化の反映、レスポンスの内容を、対象 RPC が持つ公開結果ごとに確かめる。「この RPC のテストを書いて」「handler のテストを書いて」「API テストを足して」と言われたときに使う。handler の単体テスト、偽の usecase やリポジトリへの差し替え、業務の境界値、SQL、全テーブル・全カラムの突き合わせ、usecase の 5 観点、ログの有無は対象外として、それぞれの層のテスト規約へ返す。
---

# test-handler

[工程順序の正本](playbook.yml)を最初に読み、同じagentが\`steps\`を宣言順に実行する。YAMLは工程順序を決め、各工程の判断内容と根拠はこの本文と参照資料を実読して評価する。失敗時は成功扱いせず停止して、完了工程、根拠、未決を残し、再開時は最初の未完了工程から続ける。

これは、**Connect-RPC の handler を公開 API として叩くテスト（API テスト）の書き方**である。本番と同じ組み立て関数で server を作り、`httptest.NewServer` で起動し、生成クライアントで RPC を呼び、返った `connect.Code`・公開文言・レスポンス・DB の反映を確かめる。差し替えるのは認可 interceptor 1 つだけで、usecase・リポジトリ・tx・DB は本物を通す。

これは、**handler の単体テストではない**。server struct のメソッドを直接呼ぶと interceptor を通らず、Code への翻訳も認可も検証できない。**依存の差し替えでもない**。偽の usecase・偽のリポジトリ・in-memory DB は使わない（古典派）。**下の層の再演でもない**。業務の境界値はドメインのテスト、全テーブル全行の突き合わせと DB 制約は永続化層のテスト、tx 境界と複数集約の協調は usecase のテストが確定済みで、ここでは二重に検証しない。テストの形（表・識別・Given・Then・`require` / `assert`）はテストの形の共通規則に従い、この規約はその上に「何を・どう起動して・何で確かめるか」だけを足す。

前提: Go 1.27・`connectrpc.com/connect` v1.21.0（v2 alpha は採らない）・`google.golang.org/protobuf`・`github.com/jackc/pgx/v5`・`github.com/ory/dockertest/v4`（起動は永続化層のテスト支援 `rdbtest.Start` が担う）・`github.com/stretchr/testify`。題材のディレクトリは import path を短くするため平らにしている（`example.com/roomflow/{reservation,rdb,tx,usecase,handler,reqctx}`、生成物は `gen/roomflowv1` と `gen/roomflowv1/roomflowv1connect`）。実際の配置は上位の開発規約が決める。

## 規約

| # | 柱 | 一言で | 正本 |
|---|---|---|---|
| 1 | 何をテストするか | proto ↔ 入力の変換・Code の翻訳と公開文言・認可・永続化の反映・レスポンス。業務境界値・SQL・全カラム・usecase の観点・ログは書かない。ケース数は対象 RPC の相異なる公開結果から決める | [what-to-test.md](references/what-to-test.md) |
| 2 | 起動と差し替え | `run` と同じ組み立て関数 `NewMux(Deps{Pool, Logger, Clock, Auth})` に実 DB（`rdbtest.Start`・`TestMain` 1 点）・固定 `Clock`・主体注入 interceptor を渡して `httptest.NewServer` に載せ、生成クライアントで叩く。直列 | [server-setup.md](references/server-setup.md) |
| 3 | テーブルの形 | `seed{Table}` / `caller` / `req` → `wantCode` / `wantMessage` / `wantResp` / `want{Table}`。ループ本体は Reset → Seed → 呼び出し → `connect.CodeOf` → 反映の読み取り | [table-shape.md](references/table-shape.md) |

## 手順

1. **対象の RPC を 1 つ決める。** テスト関数は `Test{Server 型}_{RPC 名}`（`TestReservationServer_ConfirmReservation`）で、1 RPC につき 1 つ。ファイルは server 実装のファイル名に `_test` を付けたもの。完了条件: 同じ RPC のテスト関数が他に無い
2. **組み立て関数と差し替え点を確かめる。** `run` が呼ぶ組み立て関数（[server-setup.md](references/server-setup.md) §1）が `*pgxpool.Pool`・`*slog.Logger`・`Clock`・認可 interceptor を引数で受けていること、handler が主体を ctx から読んでいること。完了条件: `newTestServer(t)` がその関数を呼ぶだけで書ける
3. **`main_test.go` を置く（無ければ）。** `TestMain` で `rdbtest.Start` を 1 回呼び、`pool` を package 変数に持つ。`newTestServer(t)` も同じファイルに置く。完了条件: このディレクトリに `TestMain` が 1 つで、`main_test.go` にあるのは `pool`（または `*rdbtest.DB`）・`now`・`TestMain`・起動と組み立てを支える関数だけ
4. **ケースを選ぶ。** [what-to-test.md](references/what-to-test.md) §3 の順に、成功・その RPC が返しうる sentinel ごとの Code と公開文言・主体無し・他人・入力不正を列挙する。同じ Code でも公開文言を決める sentinel が異なる経路は別に確かめる。RPC ごとの BDD を持つ API 仕様の資料があれば、その ID・見出し・gherkin を `id` / `name` / `description` へ写し、無ければ生成した id と業務語の `name`、Given / When / Then の `description`。完了条件: 実装と公開エラー対応表から到達できる各公開結果がケースに対応し、同じ結果経路へ入力値だけを変えた重複が無い
5. **表とループ本体を書く。** [table-shape.md](references/table-shape.md) の形を写す。`wantMessage` は sentinel の文言を `.Error()` で参照し、文字列を直書きしない。反映は成功ケースだけ `want{Table}` の射影で見る。完了条件: `description` の各行がフィールドの値で説明でき、ループ本体にケースを選り分ける分岐が無い
6. **検証する。** Docker が動く環境で実行する
   ```bash
   go vet ./...
   go test -count=1 ./handler/...
   go test -count=1 -run 'TestReservationServer_ConfirmReservation/c4e1a8_' ./handler/...   # 足したケースを 1 つずつ単独で
   ```
   続けて、テストの形の共通規則が持つケース識別の機械検査（package・`id` の一意・`id` / `name` / `description` の並び・gherkin の書式）を同じディレクトリに対して通す。完了条件: すべて通り、単独実行でも通る
7. **報告する。** 下の「報告」

## 停止条件

- `run` の中で組み立てが閉じていて、テストから呼べる組み立て関数が無い → 書かない。組み立て関数を切り出すことを handler の実装側へ返して止まる
- 認可 interceptor が主体を ctx に載せる形になっていない（handler が検証器を直接呼ぶ・主体を引数で受ける）→ 差し替え点が無い。実装側へ返して止まる
- handler か usecase が `time.Now()` を直接呼んでいて `Clock` が無い → 期限のケースが書けない。実装側へ返して止まる
- その RPC が返す sentinel が Code の対応表に無く `Internal` になる → 表に足すか `Internal` でよいかをエラーの規約へ返して止まる。`Internal` を期待値に書かない
- 選んだケースが公開結果、認可、入力変換、反映のいずれにも対応しない → 下位層の関心を持ち込んでいる。対応するドメイン・永続化層・usecase のテストへ返す
- Docker が無い → テストは書けるが実行できない。実行未了として報告し、「テストした」と書かない

## チェックリスト（機械で言えないことだけ）

- [ ] 1 RPC に 1 テスト関数。server のメソッドを直接呼んでいない
- [ ] `newTestServer(t)` は `run` と同じ組み立て関数を呼ぶだけで、usecase・リポジトリ・tx を自分で組んでいない
- [ ] 差し替えは認可 interceptor 1 つ。偽の usecase・リポジトリ・DB が無い
- [ ] `Clock` は固定値 `now`。時刻は server が決め、要求は運ばない。期限前・期限後は前提の `expires_at` を `now` の前後に置いて表し、表に別の時刻を持っていない
- [ ] `TestMain` は `main_test.go` の 1 つだけ。`t.Parallel()` が無く、ループ直前のコメントが共有 DB を名指ししている
- [ ] 成功・到達可能な sentinel ごとの Code と公開文言・主体無し・他人・入力不正が揃い、同じ公開結果経路へ入力値だけを変えた重複が無い
- [ ] `wantCode` は `connect.Code` の値、`wantMessage` は sentinel の `.Error()`。`Internal` と文字列直書きが無い
- [ ] `wantResp` は射影の struct で、proto message そのものを `assert.Equal` していない
- [ ] `want{Table}` は成功ケースだけにあり、反映が起きるテーブルだけ、射影だけを見ている
- [ ] 業務の境界値（隣接・同時刻）・DB 制約・同時実行・tx の rollback を書いていない
- [ ] logger は `slog.DiscardHandler`。ログの出力を検証していない

## 報告

- 対象 RPC とテスト関数名、`newTestServer(t)` が呼ぶ組み立て関数の名前
- ケース数と内訳: 成功 / sentinel ごとの拒否（sentinel と Code の対）/ 主体無し / 他人 / 入力不正。API 仕様の資料があるなら、写した ID と書かなかった ID（理由）
- 反映を見たテーブルと射影のフィールド
- 検証の結果（`go vet` / `go test` / 単独実行 / 形の機械検査）。Docker が無く実行できなかったなら、その旨
- 実装側へ返した論点（組み立て関数の切り出し、差し替え点、`Clock`、対応表に無い sentinel）
