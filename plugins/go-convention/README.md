# go-convention

**Go 1.27 の実装とテストの規約を、関心ごとに分けた 14 の自己完結skillと、層ごとの TDD 入口 4 つから適用します。** package manifestが`skills/<name>/SKILL.md`を直接公開し、規約の正本は各skill、工程順序の正本は同じdirectoryの`playbook.yml` v2にあります。同じagentが`agent_work: invoking_agent`の工程を宣言順に実行します。

## これは何か／何ではないか

これは、Go でドメイン駆動設計の層（ドメインモデル・永続化・usecase・handler）と横断的関心事（エラー・ログ）とテストを、同じ前提（typestate の集約、完全コンストラクタの値オブジェクト、sqlc + pgx、Connect-RPC、古典派のテスト、BDD 資料の ID をそのまま使うテスト）で書くための規約です。

これは、層とは何か・開発プロセス（内側から外へ、BDD 通過ゲート、ATDD）を決めるものではありません。確定済みの論理責務と集約境界を受け取り、Go 固有の package 配置へ写すところからを扱います。

## 入口

| 入口 | 何をするか |
|---|---|
| `write-go-code` | Go 1.27 のコーディング規約で書く・直す |
| `apply-go-package-layout` | 確定済みの論理責務を Go の package 配置と import 方向へ写す |
| `implement-domain-model` | domain-model 資料から値オブジェクト・エンティティ・集約を実装する |
| `implement-repository` | 集約の永続化ポートを sqlc + pgx で実装する（通常型・イベント型） |
| `implement-query-service` | CQRS の読み取り側を sqlc で実装する |
| `implement-usecase` | command / query の usecase を実装する |
| `implement-handler` | Connect-RPC の handler と interceptor を実装する |
| `handle-errors` | エラーの作り方・包み方・翻訳 |
| `write-logs` | log/slog の出し方と出す場所 |
| `apply-go-test-convention` | テストの形（テーブル駆動・id/name/description・Given/When/Then） |
| `test-domain-model` | 集約・エンティティ・値オブジェクトのテストを資料の BDD から書く |
| `test-repository` | 永続化層（リポジトリ・query service）のテストをデータモデル資料から書く |
| `test-usecase` | usecase のテストを 5 観点で書く |
| `test-handler` | handler のテストを本番同等 DI で書く |
| `develop-domain-model` | ドメイン層の 1 単位（集約または値オブジェクト）を、テスト → 赤 → 実装 → 緑 → 整える の順で完成させる |
| `develop-repository` | 永続化層の 1 単位（リポジトリまたは query service）を同じ順で完成させる |
| `develop-usecase` | usecase 1 つを同じ順で完成させる |
| `develop-handler` | RPC 1 つを同じ順で完成させる（エラーの対応表とログも揃える） |

`develop-<layer>` は `playbook.yml` の `skill:` 工程で同じ package の `test-<layer>` → `implement-<layer>`（永続化層は対象により `implement-repository` / `implement-query-service`）→ `write-go-code`（必要なら `handle-errors` / `write-logs`）を順に呼びます。テストの規約と実装の規約は別 file のままです。

## 入力

- 対象のパッケージと、書く・直す対象（型・関数・RPC）
- BDD 資料（domain-rule / domain-model / rdb-logical-data-modeling）があればその絶対パス
- 既存のコード・テスト（あれば）
- `references`: 追加で従う資料の絶対パス配列（任意）。プロジェクト固有の規約は対象 repository の AGENTS.md / CLAUDE.md と `references` で渡します

## 出力

各skillの `SKILL.md`「報告」の節を参照してください。

## 設定

独自設定はありません。前提は Go 1.27 と、各 skill が明記する最新版のライブラリです。
