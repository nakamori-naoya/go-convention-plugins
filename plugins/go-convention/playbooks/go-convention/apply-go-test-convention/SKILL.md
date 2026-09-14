---
name: apply-go-test-convention
description: Go のテストの形を共通規約に揃える。「このテストを規約に合わせて」と言われたときに使う独立プレイブック。内部skill `apply-go-test-convention` へルーティングする。
---

# apply-go-test-convention

同梱の`playbook.yml`を公開入口とし、内部skill`apply-go-test-convention`（`skills/apply-go-test-convention/SKILL.md`）へ明示的にルーティングする。

## 実行

1. package root を決める。Claude Code では`${CLAUDE_PLUGIN_ROOT}`が package root である。Codex ではこの`SKILL.md`があるdirectoryの3つ上（`playbooks/go-convention/apply-go-test-convention` の親の親の親）が package root である。
2. `bash "<package root>/playbooks/go-convention/apply-go-test-convention/scripts/prepare.sh"`で、この入口と対応する内部skillが同じ配布パッケージ内にあることを検査する。
3. `<package root>/skills/apply-go-test-convention/SKILL.md`を読み、その手順に従って実行する。手順、入力、出力、停止条件は内部skillの`SKILL.md`を正本とし、この入口は何も足さない。
4. `scripts/resolve.sh`は公開入口と内部skillの対応を機械可読なJSONとして返す。

この入口は同じ配布パッケージの中だけで完結し、他の配布物に依存しない。
