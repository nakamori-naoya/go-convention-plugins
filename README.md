# Go Convention Plugins

Go 1.27 の実装とテストの規約を関心ごとに分けて配布する、Claude Code / Codex 両対応の marketplace です。公開 package は `go-convention` 1 件で、15 の自己完結skill（規約 14 と TDD の 1 単位の入口 1。[plugin README](plugins/go-convention/README.md) の表）をpackage manifestから直接公開します。規約の基準資料は各skillの `SKILL.md` と `references/`、工程順序の定義は各skill直下の`playbook.yml` v2です。

## こんなときに使う

**Go で DDD の層（ドメインモデル・永続化・usecase・handler）と横断的関心事（エラー・ログ）とテストを、同じ前提で書きたい・直したいときに使う。**

- ドメインモデルの資料から、状態ごとに型を分けた集約と、生成の時点で検証する値オブジェクトを実装したい
- データモデルの資料の BDD を、Before を作り、操作し、After に挙がったテーブルを突き合わせるリポジトリのテストにしたい
- 資料の `BDD-NNN` をそのまま `id` にしたテーブル駆動のテストを書きたい
- エラーを15の分類から定義し、境界の表で応答、再処理、ログレベルを決め、境界で一度だけ記録する形に揃えたい
- 集約、リポジトリ、usecase、RPC を一単位ずつ、テストを先に赤で置いて実装で緑にし、整えるまでを一サイクルで進めたい（TDD）

## 利用例

```text
この domain-model 資料の「貸出」集約を Go で実装して。
```

```text
この集約のテストを、業務知識の資料の BDD から書いて。
```

```text
このリポジトリのテストを rdb-logical-data-modeling 資料の BDD から書いて。After に挙がったテーブルを突き合わせて。
```

```text
この集約を TDD で実装して。テストを先に赤で置いてから実装して、整えるところまで。
```

## インストール

インストールするのは `go-convention@go-convention` です。外部プラグインの追加は不要です。

### Codex

利用する Codex と同じ設定環境で実行してください。

```bash
codex plugin marketplace add nakamori-naoya/go-convention-plugins
codex plugin add go-convention@go-convention
codex plugin list
```

一覧で導入先を確認し、新しい会話で利用してください。

### Claude Code

次は自分の全プロジェクトで使う例です。このプロジェクトのチームで共有する場合は `project`、このプロジェクトで自分だけが使う場合は `local` に変更し、利用先のディレクトリで実行してください。

```bash
CLAUDE_PLUGIN_SCOPE=user
claude plugin marketplace add nakamori-naoya/go-convention-plugins --scope "$CLAUDE_PLUGIN_SCOPE"
claude plugin install go-convention@go-convention --scope "$CLAUDE_PLUGIN_SCOPE"
claude plugin list
```

一覧で導入を確認し、Claude Code を再起動してください。すでに導入しているパッケージは、次の更新手順を使ってください。

## 更新する

GitHub から登録した marketplace を更新し、その公開パッケージを更新します。新規インストールと同じ Codex の設定環境、Claude Code の適用範囲を使ってください。

### Codex

```bash
codex plugin marketplace upgrade go-convention
codex plugin add go-convention@go-convention
codex plugin list
```

更新後は新しい会話で確認してください。ローカルのパスから marketplace を登録した場合は、Git 版の更新コマンドではなく、その登録先のソースを更新してから追加し直します。

### Claude Code

```bash
# インストール時に合わせて user / project / local を選ぶ
CLAUDE_PLUGIN_SCOPE=user
claude plugin marketplace update go-convention
claude plugin update go-convention@go-convention --scope "$CLAUDE_PLUGIN_SCOPE"
claude plugin list
```

更新後は Claude Code を再起動してください。

marketplace の取得と、インストール済みパッケージの更新は分けて確認します。同じバージョンとして公開された変更は、更新コマンドだけでは反映されない場合があります。「最新」と表示された場合は公開バージョンを確認し、キャッシュ内のファイルを直接編集しないでください。

## 配布する plugin

- `go-convention`: 15 の入口（Go package 配置・コーディング・ドメインモデル・リポジトリ・query service・usecase・handler・エラー・ログ・テストの形・ドメインモデルのテスト・永続化層のテスト・usecase のテスト・handler のテスト、および TDD の 1 単位の入口 `develop-go-unit`）

`develop-go-unit` は、`development-convention` package の `develop-inside-out`（言語非依存の ATDD 工程: 一場面の受け入れテストを先に赤で置き、内側の層から外側へゲートを通して進める）の各層を Go で実装するときの 1 単位です。`develop-inside-out` が層の順序とゲートを決め、`develop-go-unit` がその層の中を「テスト → 赤 → 実装 → 緑 → 整える」で完成させます。テストの規約（`test-*`）と実装の規約（`implement-*`）は別 file のまま、`develop-go-unit` の `playbook.yml` が層に応じて順に呼びます。

利用契約は [plugin README](plugins/go-convention/README.md) を参照してください。決定の経緯は [decisions/go-convention-plugins.jsonl](decisions/go-convention-plugins.jsonl) にあります。テストの形の実例は [tests/examples/](tests/examples/) にあり、[examples.md](plugins/go-convention/skills/apply-go-test-convention/references/examples.md) と同一のコードです。

## 検証

```bash
bash scripts/validate.sh
```

検査の内容と、通ったとき言えることは [VALIDATION.md](VALIDATION.md) を参照してください。
