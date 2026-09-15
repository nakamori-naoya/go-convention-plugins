# AGENTS.md

この repository は、Go 1.27 の実装とテストの規約を関心ごとに分けて配布する source である。

- marketplace へ公開するインストール対象は `go-convention` package 1 件だけにする。個々の入口や内部 skill を別のインストール対象として公開しない。
- 公開入口は `plugins/go-convention/playbooks/go-convention/<name>/` の 14 件で、それぞれ同名の内部 skill `plugins/go-convention/skills/<name>/` へ 1 工程でルーティングするだけにし、内容を持たない。入口の一覧は両 runtime の manifest（`metadata.harness.playbooks` / `internalPlugins`）が正本で、Codex と Claude の manifest は同一に保つ。
- 内部 skill は自己完結にする。自分の `SKILL.md`、`references/`、`scripts/` だけで仕事が完了し、兄弟 skill の名前・path・実行済み状態を前提にしない。`skills/**/*.md` に兄弟 skill の名前と「playbook」「プレイブック」を書かない（root の `scripts/validate-plugin-repository.py` が落とす）。他の関心に触れるときは「テストの形の共通規則」「エラーの規約」のように語で書く。
- 規約の正本は各 skill の `SKILL.md` と `references/*.md` である。複数の skill が同じ規則を持つときは、各 skill が自分の言葉で必要な分だけ持つ。同期スクリプトや生成器を作らず、整合はレビュー（エージェントによる読み合わせ）で確かめる。
- 決定の正本は `decisions/go-convention-plugins.jsonl` である。規約を変えるときは決定を先に足す。
- 例はすべて文書上のコード片で、動かす必要はないが Go 1.27 でコンパイルできる形で書く。例外は `tests/examples/` の 1 つの Go モジュール（3 package）で、テストの形の skill の `references/examples.md` と同一に保ち、`check-cases.py` の正例・負例に使う。
- 機械検査は決定論的な述語だけに限る（identity の一致、入口と内部 skill の対応、reference の到達性、`check-cases.py` の述語、shell 構文）。文体・整合性・好みは script で検出せず、エージェントに読ませて評価する。
- 逃げ道・「〜してもよい」の連発・smell の列挙・反論と応答の羅列をしない。後方互換は考慮しない。
- 変更後は `bash scripts/validate.sh` と、workspace root の `bash ../scripts/validate.sh "$(pwd)"` を実行する。
- install cache は編集せず、この source を正本として変更する。
