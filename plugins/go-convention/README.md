# go-convention

**Go 1.27 の実装とテストの規約を、層ごとの4つの skill と、層をまたぐ5つの skill から適用します。** package manifestが`skills/<name>/SKILL.md`を直接公開し、規約の基準資料は各skillの`SKILL.md`と`references/`です。

## これは何か／何ではないか

これは、Go でドメイン駆動設計の層（ドメインモデル・永続化・usecase・handler）と横断的関心事（エラー・ログ）とテストを、同じ前提で書くための規約です。前提は、状態ごとに型を分けた集約、生成の時点で検証する値オブジェクト、sqlc と pgx、Connect-RPC、実物を通す古典派のテスト、BDD 資料の ID をそのまま使うテストです。

これは、層とは何か・開発プロセス（内側から外へ、BDD 通過ゲート、ATDD）を決めるものではありません。確定済みの論理責務と集約境界を受け取り、Go 固有の package 配置へ写すところからを扱います。

## 入口

層の skill は、実装とそのテストを一つに持ち、テストを先に赤で置いてから実装する一つの単位を仕上げます。

| 入口 | 何をするか |
|---|---|
| `develop-domain-model` | ドメインモデルの資料から、値オブジェクト、集約、イベント、永続化ポートとそのテストを書く |
| `develop-repository` | 集約のリポジトリ、手順の口、Query の実装とその実 DB のテストを sqlc と pgx で書く |
| `develop-usecase` | command、単純なパターンの手順、query の usecase と、配線と境界を確かめるテストを書く |
| `develop-handler` | Connect-RPC の入口、interceptor、組み立てと、本番の組み立てを通す API のテストを書く |
| `write-go-code` | 言語の規約（型で業務を運ぶ、丸めない、関数の形、interface、名前、コメント、package の木、ツール）で書く・直す |
| `apply-crosscutting-contracts` | トランザクション、ctx の executor、翻訳、時計、採番、分類の表を引く関数の契約を定める |
| `handle-errors` | エラーを15の分類から定義し、運び、翻訳し、付け替え、応答の表と処理の表で扱う |
| `write-logs` | ログレベルの意味と分類からの表、境界で一度だけ記録する場所、logger の注入、属性と秘匿 |
| `apply-go-test-convention` | テストの共通の形（テーブル駆動、id / name / description、差し替えてよい境界、Builder、実 DB） |

層の順序とゲート、赤の定義、一つの単位の進め方は、`development-convention` の `develop-inside-out` が持ちます。

## 入力

- 対象のパッケージと、書く・直す対象（型・関数・RPC）
- BDD 資料（domain-rule / domain-model / rdb-logical-data-modeling）があればその絶対パス
- 既存のコード・テスト（あれば）
- `references`: 追加で従う資料の絶対パス配列（任意）。プロジェクト固有の規約は対象 repository の AGENTS.md / CLAUDE.md と `references` で渡します

## 出力

各skillの `SKILL.md`「報告」の節を参照してください。

## 設定

独自設定はありません。前提は Go 1.27 と、各 skill が明記する最新版のライブラリです。
