> 作業を始める前に、workspace規約入口 `/Users/naoya-nakamoriq/Documents/Github/harness-pluginsv2/AGENTS.md` を読み、そこから指定される共通規約とこのrepository固有の規則を適用する。

# AGENTS.md

この repository は、Go 1.27 の実装とテストの規約を関心ごとに分けて配布する source である。

- marketplace へ公開するインストール対象は `go-convention` package 1 件だけにする。個々のskillを別のインストール対象として公開しない。
- 両runtimeのpackage manifestは `plugins/go-convention/skills/<name>/` の自己完結skill 9件（層の4件と、層をまたぐ5件）を直接公開し、同一に保つ。
- 各skillは自己完結にする。自分の `SKILL.md`、`references/`、`scripts/` だけで仕事が完了し、兄弟skillの名前・path・実行済み状態を前提にしない。兄弟identityへの明示依存の有無は構造検査し、文章の意味上の依存は実読して評価する。
- 層の skill（`develop-domain-model`、`develop-repository`、`develop-usecase`、`develop-handler`）は、その層の実装とテストを一つに持ち、テストを先に赤で置いてから実装する一つの単位を仕上げる。一つの単位の進め方と赤の定義は持たず、development-convention の `develop-inside-out` に従う。
- 規約の基準資料は各 skill の `SKILL.md` と `references/*.md` である。複数の skill が同じ規則を持つときは、各 skill が自分の言葉で必要な分だけ持つ。同期スクリプトや生成器を作らず、整合はレビュー（エージェントによる読み合わせ）で確かめる。
- 決定の基準資料は `decisions/go-convention-plugins.jsonl` である。規約を変えるときは決定を先に足す。
- 例はすべて文書上のコード片で、動かす必要はないが Go 1.27 でコンパイルできる形で書く。例外は `tests/examples/` の 1 つの Go モジュール（3 package）で、テストの形の skill の `references/examples.md` と同一に保ち、`check-cases.py` の正例・負例に使う。
- 機械検査は決定論的な述語だけに限る（identity の一致、manifestと直接公開skillの対応、reference の到達性、`check-cases.py` の述語、shell 構文）。文体・整合性・好みは script で検出せず、エージェントに読ませて評価する。
- 逃げ道・「〜してもよい」の連発・smell の列挙・反論と応答の羅列をしない。後方互換は考慮しない。
- 変更後は `bash scripts/validate.sh` と、workspace root の `bash ../scripts/validate.sh "$(pwd)"` を実行する。
- install cache は編集せず、この source を参照元として変更する。

## 検査スクリプトは、意味が一意に決まることだけを判定する

このrepositoryの検査スクリプト（validate、lint、verify、checkなど、名前を問わない）が判定してよいのは、ファイルや見出しの有無、識別子や版の一致、宣言と配置の対応、禁止された書き方の有無のように、入力と基準資料から意味が決定論的に一意に決まることだけである。読んで解釈しないと決まらないことや、件数や語の出現のような品質の代わりの指標は判定せず、エージェントが読んで評価する（意味評価）。判定が一意に決まることを宣言できない検査は作らず、詳しい条件は `/Users/naoya-nakamoriq/Documents/Github/harness-pluginsv2/.agents/rules/deterministic-validation.md` に従う。
