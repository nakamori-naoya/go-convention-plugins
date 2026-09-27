#!/usr/bin/env bash
# 共通の準備で、フォローの資料と、アカウントの業務が先に置いた利用者IDを持つ repository を作る。
set -euo pipefail
CASE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec bash "$CASE_DIR/../../scaffold.sh" "$CASE_DIR/.." フォロー "$CASE_DIR/fixture"
