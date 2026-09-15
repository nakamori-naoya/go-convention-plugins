#!/usr/bin/env bash
set -euo pipefail
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/../../../.." && pwd)}"
test -f "$root/skills/apply-go-package-layout/SKILL.md"
test -f "$root/playbooks/go-convention/apply-go-package-layout/playbook.yml"
printf '%s\n' "$root/playbooks/go-convention/apply-go-package-layout"
