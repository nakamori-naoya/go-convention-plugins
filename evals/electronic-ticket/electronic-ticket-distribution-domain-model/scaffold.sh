#!/usr/bin/env bash
# 共通の準備で、チケットの資料を持つ repository を作る。先に置く内側の層は無い。
set -euo pipefail
CASE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec bash "$CASE_DIR/../../scaffold.sh" "$CASE_DIR/.." チケット
