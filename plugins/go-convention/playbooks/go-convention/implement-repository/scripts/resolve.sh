#!/usr/bin/env bash
set -euo pipefail
PLAYBOOK_ROOT=$("$(dirname "${BASH_SOURCE[0]}")/prepare.sh")
ID=$(basename "$PLAYBOOK_ROOT")
printf '{"playbook":"%s","skill":"%s","route":"skill"}\n' "$ID" "$ID"
