# go-convention

**Go 1.27 の実装とテストの規約を、関心ごとに分けた 14 の自己完結skillと、TDD の 1 単位の入口 1 つから適用します。** package manifestが`skills/<name>/SKILL.md`を直接公開し、規約の基準資料は各skill、工程順序の定義は同じdirectoryの`playbook.yml` v2にあります。同じagentが`agent_work: invoking_agent`の工程を宣言順に実行します。

## これは何か／何ではないか

これは、Go でドメイン駆動設計の層（ドメインモデル・永続化・usecase・handler）と横断的関心事（エラー・ログ）とテストを、同じ前提で書くための規約です。前提は、状態ごとに型を分けた集約、生成の時点で検証する値オブジェクト、sqlc と pgx、Connect-RPC、実物を通す古典派のテスト、BDD 資料の ID をそのまま使うテストです。

これは、層とは何か・開発プロセス（内側から外へ、BDD 通過ゲート、ATDD）を決めるものではありません。確定済みの論理責務と集約境界を受け取り、Go 固有の package 配置へ写すところからを扱います。

## 入口

| 入口 | 何をするか |
|---|---|
| `write-go-code` | Go 1.27 の言語レベルの規約（プリミティブを使わない、丸めない、関数の形、interface、命名、コメント、ツール）で書く・直す |
| `apply-go-package-layout` | 確定済みの論理責務を Go の package 配置と import 方向へ写す |
| `implement-domain-model` | ドメインモデルの資料から、値オブジェクト、集約、イベント、永続化ポートを実装する |
| `implement-repository` | 集約の永続化ポートと単純なパターンの口（DB へのアクセスを受け持つ関数の集まり）を sqlc と pgx で実装する |
| `implement-query-service` | CQRS の読み取り側を sqlc で実装する |
| `implement-usecase` | command、単純なパターンの手順、query の usecase を実装する |
| `implement-handler` | Connect-RPC の handler と interceptor を実装する |
| `handle-errors` | エラーを15の分類から定義し、運び、翻訳し、応答の表と処理の表で扱う |
| `write-logs` | ログレベルの意味と分類からの表、境界で 1 回だけ記録する場所、logger の注入、属性と秘匿 |
| `apply-go-test-convention` | テストの形（テーブル駆動・id/name/description・Given/When/Then） |
| `test-domain-model` | 集約・エンティティ・値オブジェクトのテストを資料の BDD から書く |
| `test-repository` | 永続化層（リポジトリ・query service）のテストをデータモデル資料から書く |
| `test-usecase` | usecase のテストを、配線と境界だけを実物で確かめる形で書く |
| `test-handler` | API のテストを、本番の組み立てで外部の境界だけを差し替えて書く |
| `develop-go-unit` | Go の 1 単位（ドメイン、リポジトリ、Query の実装、usecase、入口のどれか一つ）を、テスト → 赤 → 実装 → 緑 → 整える の順で完成させる |

`develop-go-unit` は `playbook.yml` の `skill:` 工程で、層（`unit.layer`）に応じた同じ package の `test-*` → `implement-*` → `write-go-code`（必要なら `handle-errors` / `write-logs`）を順に呼びます。テストの規約と実装の規約は別 file のままです。

## 入力

- 対象のパッケージと、書く・直す対象（型・関数・RPC）
- BDD 資料（domain-rule / domain-model / rdb-logical-data-modeling）があればその絶対パス
- 既存のコード・テスト（あれば）
- `references`: 追加で従う資料の絶対パス配列（任意）。プロジェクト固有の規約は対象 repository の AGENTS.md / CLAUDE.md と `references` で渡します

## 出力

各skillの `SKILL.md`「報告」の節を参照してください。

## 設定

独自設定はありません。前提は Go 1.27 と、各 skill が明記する最新版のライブラリです。
