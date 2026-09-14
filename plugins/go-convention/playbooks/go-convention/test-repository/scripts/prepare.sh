#!/usr/bin/env bash
set -euo pipefail
PLAYBOOK_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PACKAGE_ROOT=$(cd "$PLAYBOOK_ROOT/../../.." && pwd)
ID=$(basename "$PLAYBOOK_ROOT")
[ -f "$PLAYBOOK_ROOT/playbook.yml" ] || { echo "[error] playbook.ymlが無い" >&2; exit 2; }
[ -f "$PACKAGE_ROOT/skills/$ID/SKILL.md" ] || { echo "[error] 対応する内部skillが無い: $ID" >&2; exit 2; }
printf '%s\n' "$PLAYBOOK_ROOT"
