---
name: apply-go-package-layout
description: 確定済みの論理責務と集約境界を Go の package 配置と import 方向へ写す。「Go の package 構成を決めて」と言われたときに使う独立プレイブック。内部skill `apply-go-package-layout` へルーティングする。
---

# apply-go-package-layout

同梱の`playbook.yml`を公開入口とし、内部skill`apply-go-package-layout`（`skills/apply-go-package-layout/SKILL.md`）へ明示的にルーティングする。

## 実行

1. package root を決める。Claude Code では`${CLAUDE_PLUGIN_ROOT}`が package root である。Codex ではこの`SKILL.md`があるdirectoryの3つ上が package root である。
2. `bash "<package root>/playbooks/go-convention/apply-go-package-layout/scripts/prepare.sh"`を実行する。
3. `<package root>/skills/apply-go-package-layout/SKILL.md`を読み、その手順だけに従う。
4. `scripts/resolve.sh`は対応を機械可読なJSONとして返す。

