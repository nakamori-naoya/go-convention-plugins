---
name: go-convention-internal-test-usecase
description: usecase（command / query）のテストを、実 DB（dockertest の PostgreSQL）・実リポジトリ・実 tx・実 query service で通し、5 観点（入力解決・複数集約の協調・ソース選択・トランザクション境界・コマンド呼び分けと永続化）の配線だけを DB の状態と返り値で確かめる形で書く・直す。「この usecase のテストを書いて」「usecase のテストが厚すぎないか見て」「tx 境界のテストを足して」と言われたときに使う。業務ルールの網羅（ドメイン層）、全テーブル・全カラムの突き合わせと SQL の正確さ（永続化層）、proto 変換・connect.Code・認可（handler）、テストの形の共通規則そのものは対象外として、それぞれの規約へ返す。
---

# test-usecase

これは、**usecase の `Execute` を実物（実 DB・実リポジトリ・実 tx・実 query service）で通し、usecase が持つ配線 —— 入力の解決、複数集約の協調、読む先の選択、トランザクション境界、コマンドの呼び分けと永続化 —— が正しいことを、DB の状態と返り値で確かめる規約**である。usecase は業務判断を持たない薄い層なので、テストも薄い。ケースは 5 観点の分岐の数だけ書き、それ以外は書かない。

これは、**業務ルールのテストではない**。値オブジェクトの制約・境界値、集約の不変条件・状態遷移・拒む理由はドメイン層のテストが網羅済みで、ここで入力値を変えて再検証しない。**永続化のテストでもない**。全テーブル・全カラムの突き合わせ、イベント表の連結、楽観ロック、SQL の JOIN / WHERE は永続化層のテストの責務で、ここでは観点が見るテーブルだけを読む。**API のテストでもない**。proto ↔ Input の変換、`connect.Code` への翻訳、認可は handler のテストが見る。**mock の interaction test でもない**。リポジトリ・tx・query service を偽物に置き換えず、呼び出し回数や引数を検証しない。

前提: Go 1.27、`github.com/stretchr/testify`、`github.com/jackc/pgx/v5`（`pgxpool` / `pgtype`）、`github.com/ory/dockertest/v4`（起動は永続化層のテスト支援 `rdbtest.Start` が担い、usecase のテストは `TestMain` から呼ぶだけ）、sqlc（`sql_package: "pgx/v5"`）が生成した行の型 `sqlcgen.*`。テストの形（無名 struct のテーブル・`id` / `name` / `description`・`want*` / `wantErr`・`require` / `assert`）はテストの形の共通規則に従い、この skill はその上に usecase 固有の形を足す。題材は貸会議室予約 RoomFlow（module `example.com/roomflow`）で、ディレクトリ構成は上位の開発規約が決めるため、例は import path を短くするために `reservation` / `rdb` / `query` / `tx` / `usecase` と平らにしている。

## 規約

| # | 柱 | 一言で | 正本 |
|---|---|---|---|
| 1 | 5 観点 | 入力解決・複数集約の協調・ソース選択・tx 境界・コマンド呼び分けと永続化。ケースはこの 5 つのどれかに属し、どれにも属さないケースは書かない | [five-viewpoints.md](references/five-viewpoints.md) |
| 2 | 書かない観点 | VO の制約・集約の不変条件・SQL・全テーブル全カラム・proto 変換・`connect.Code`・認可。それぞれどの層の責務かを言える | [five-viewpoints.md](references/five-viewpoints.md) |
| 3 | 厚さ | 1 usecase のケース数 = 5 観点の分岐数（入力解決 1〜2 / 協調 1〜3 / ソース選択 0〜3 / tx 境界 2 / 呼び分け 1〜2）。同じルールで入力値だけ変えるケースは書かない | [five-viewpoints.md](references/five-viewpoints.md) |
| 4 | 実物で通す | 実 DB（dockertest。`main_test.go` の `TestMain` 1 点・直列）、実リポジトリ、実 `tx.Manager`、実 query service。例外は決定的な `IDGenerator` だけ（時刻は `Execute` の入力 `At` に固定値を渡す）。前提投入は `rdbtest.Seed{Table}` で、集約も SQL もテストで組み立てない | [setup.md](references/setup.md) |
| 5 | テーブルの形 | `seed{Table}` → `ids` → `in`（`Execute` の引数名そのまま。時刻は `in.At`）→ `want`（query の DTO）/ `wantErr error`（sentinel）/ `want{Table}`（観点が見るテーブルだけ）。ループ本体 1 回。`id` は生成した id、`name` は観点が分かる業務語の 1 文 | [table-shape.md](references/table-shape.md) |

## 手順

1. **usecase の `Execute` を読み、5 観点に分ける。** 入力解決（primitive → VO、期間 → 範囲）、協調（別の集約・別のインスタンスの何を読み、何を変えるか）、ソース選択（入力で読む先が変わるか）、tx 境界（`Run` の中で書くテーブル）、呼び分け（復元 → 絞り込み → 操作 → `Apply*` / `Create` / `Update`、`(Result, bool)` の false）を列挙する。完了条件: `Execute` の各行がどれかの観点に割り当てられ、どれにも割り当てられない行（状態の判定・件数の解釈・計算）が無い
2. **ケースを決める。** 観点ごとに分岐の数だけケースを起こし、それぞれの Given（前提の行）・When（`in`・`ids`）・Then（`wantErr` / `want` / `want{Table}`）を業務語で書く。tx 境界の rollback は「途中の書き込みを DB 制約で失敗させる前提」を先に決める。完了条件: ケース数が 5 観点の分岐数と一致し、各ケースの `name` から観点が読める。書かない観点の表に当たるケースが無い
3. **`main_test.go` を確かめる。** package に無ければ `TestMain` を 1 点だけ書く（[setup.md](references/setup.md) §3）。あれば足さない。完了条件: `TestMain` がこの package に 1 つで、`main_test.go` にあるのは `pool`（または `*rdbtest.DB`）・`TestMain`・起動と組み立てを支える関数だけ
4. **表とループ本体を書く。** ファイルは usecase の実装ファイルと 1 対 1（`confirm_reservation.go` ↔ `confirm_reservation_test.go`）、テスト関数は `Test{Usecase}_Execute`。ループ本体は `Reset` → `Seed*` → 本番と同じコンストラクタで DI → `Execute` → `wantErr` / `want` → `Read{Table}` と `want{Table}` の突き合わせ、の 1 回。完了条件: ループ本体にケースを選り分ける分岐が無く、`t.Parallel()` が無く、テスト本文に SQL と集約の組み立てが無い
5. **足りないテスト支援を返す。** 必要な `Seed{Table}` / `Read{Table}` が `rdbtest` に無い、`IDGenerator` の固定実装が無い、途中失敗を起こす制約が DDL に無い —— いずれもテスト本文で代用せず、永続化層のテスト支援・usecase の実装・データモデルの各規約へ返す。完了条件: テスト本文に置いた回避策が無い
6. **機械検査を通す。**
   ```bash
   go vet ./...
   go test -count=1 ./usecase/...
   go test -count=1 -run 'TestConfirmReservation_Execute/9f1c2a_' ./usecase/...   # 足したケースを 1 つずつ単独で
   ```
   テストの形の共通規則が機械検査（`id` / `name` / `description` の形）を持つなら、それも通す。完了条件: すべて通り、Docker が無いときは skip ではなく失敗として現れる
7. **報告する。** 「報告」の項目を返す

## 停止条件

- 書きたいケースが 5 観点のどれにも当たらない（VO の境界値・状態違いの網羅・全カラム・エラーコード・権限） → 書かない。どの層の責務かを [five-viewpoints.md](references/five-viewpoints.md) §3 の表で示して返す
- usecase が業務判断（`Status()` の判定・件数の解釈・計算）を持っていて、その分岐を書かないとテストが通らない → テストを書かず、判断をドメインへ移すよう usecase の実装の規約へ返す
- usecase が `time.Now()` を呼んでいる（時刻は入力 `At` で受ける）、または採番を直接呼んでいて `IDGenerator` で固定できない → 書かずに usecase の実装の規約へ返す。テストで時刻を待たない・ID を正規表現で見ない
- tx 境界の rollback を起こす前提が DB 制約で作れない（途中で失敗する書き込みが無い） → mock で失敗を注入しない。DDL の制約かデータモデル資料へ返し、rollback ケースは書かずに報告へ載せる
- `rdbtest` に必要な `Seed{Table}` / `Read{Table}` / `Reset` が無い → テスト本文に SQL を書かず、永続化層のテスト支援への追加を返す
- Docker が使えない環境 → `t.Skip` しない。失敗として扱い、環境を整えるよう返す

## チェックリスト

- [ ] 各ケースの `name` から 5 観点のどれかが読める。書かない観点の表に当たるケースが無い
- [ ] ケース数が 5 観点の分岐数と一致している。同じルールで入力値だけ変えたケースが無い
- [ ] リポジトリ・tx・query service が実物で、コンストラクタが本番と同じ。`IDGenerator` 以外に差し替えが無い
- [ ] `main_test.go` の `TestMain` が package に 1 点で `rdbtest.Start` → `m.Run()` → `Close` → `os.Exit` だけを書き、package 変数は `pool` だけ。`t.Parallel()` が無く、ループ直前に直列の理由がコメントで書かれている
- [ ] 前提は `rdbtest.Reset` → `rdbtest.Seed{Table}` の行で書かれ、テスト本文に SQL・集約の `Restore*` / `Hold` が無い
- [ ] `in` は `Execute` の引数の型そのもので、時刻は `in.At` の固定値。`ids` は固定値のフィールドで、ID の生成規則を検証していない
- [ ] `wantErr` は sentinel（ドメインか `rdb`）で `require.ErrorIs`。文言の比較が無い
- [ ] `want{Table}` は観点が見るテーブルだけ。全テーブルを毎ケース突き合わせていない
- [ ] tx 境界の rollback ケースが、途中の書き込みの後に失敗する前提を持ち、`want{Table}` が前提と同じ
- [ ] 協調のケースが、読まれる側の集約の行を前提に持ち、変わる側の行を `want{Table}` で見ている
- [ ] `id` は生成した id で `BDD-` の形ではない。末尾の「テストしない BDD」の列挙が無い

## 報告

- 対象の usecase とテスト関数名、ファイルの対応（実装ファイル ↔ テストファイル）
- ケースの一覧: `id` / `name` / 観点（5 観点のどれか）。観点ごとの分岐数と合っているか
- 書かなかった観点と、その責務の層（ドメイン / 永続化 / handler）
- rollback を起こした前提（どの制約で途中失敗させたか）。書けなかったならその理由
- 仮定したテスト支援（`rdbtest` の関数、`usecasetest` の固定実装）と、無かったので返したもの
- 資料の未決を仮の値で埋めた前提（例: 基底イベントの `actor_code` に置いた「期限管理」「不利用判定」）。物理設計で値が決まったら差し替える
- 機械検査の結果（`go vet` / `go test` / 単独実行）
- 停止条件で返した論点
