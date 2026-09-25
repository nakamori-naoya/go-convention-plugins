> 共通の規約は /Users/naoya-nakamoriq/Documents/Github/harness-pluginsv2/AGENTS.md にある。ここには、この repository だけの規則を置く。

# AGENTS.md

この repository は、Go 1.27 の実装とテストの規約を関心ごとに分けて配布する source である。

- marketplace へ公開するインストール対象は `go-convention` package 1 件だけにする。個々のskillを別のインストール対象として公開しない。
- 両runtimeのpackage manifestは `plugins/go-convention/skills/<name>/` の自己完結skill 9件（層の4件と、層をまたぐ5件）を直接公開し、同一に保つ。
- 各skillは自己完結にする。自分の `SKILL.md`、`references/`、`scripts/` だけで仕事が完了し、兄弟skillの名前・path・実行済み状態を前提にしない。兄弟identityへの明示依存の有無は構造検査し、文章の意味上の依存は実読して評価する。
- 層の skill（`develop-domain-model`、`develop-repository`、`develop-usecase`、`develop-handler`）は、その層の実装とテストを一つに持ち、テストを先に赤で置いてから実装する一つの単位を仕上げる。一つの単位の進め方と赤の定義は持たず、development-convention の `develop-inside-out` に従う。
- 規約の基準資料は各 skill の `SKILL.md` と `references/*.md` である。複数の skill が同じ規則を持つときは、各 skill が自分の言葉で必要な分だけ持つ。同期スクリプトや生成器を作らず、整合はレビュー（エージェントによる読み合わせ）で確かめる。
- 決定の基準資料は `decisions/go-convention-plugins.jsonl` である。規約を変えるときは決定を先に足す。
- 例はすべて文書上のコード片で、動かす必要はないが Go 1.27 でコンパイルできる形で書く。例外は `tests/examples/` の 1 つの Go モジュール（3 package）で、テストの形の skill の `references/examples.md` と同一に保ち、`check-cases.py` の正例・負例に使う。
