#!/usr/bin/env bash
# ケースが共有する準備。空の作業場所に、手元だけの git repository（out/）を作り、Go の module の土台、
# お題の資料、ケースが先に置く内側の層を入れる。別 package の skill のファイルは harness/ へ写す。
# 作業場所の agent は外へ接続できないので、module は手元の module cache を GOPROXY にして取り、
# ツールも先に一度 build しておく。この script は作業場所の外の権限で動く。
#
#   bash scaffold.sh <お題のディレクトリ> <業務名> [先に置く内側の層のディレクトリ]
#
# 別 package の skill は兄弟 checkout（この repository と同じ親の下）から写す。マージ前の branch の skill で
# 回すときは、その branch の checkout を兄弟に並べた親を用意し、そこからこの repository を開いて回す。
set -euo pipefail

[ $# -ge 2 ] || { echo "使い方: bash scaffold.sh <お題のディレクトリ> <業務名> [内側の層]" >&2; exit 2; }
TOPIC_DIR=$(cd "$1" && pwd)
BUSINESS=$2
FIXTURE=${3:-}
EVALS_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPOSITORY=$(cd "$EVALS_DIR/.." && pwd)
WORKSPACE=$(cd "$(dirname "$REPOSITORY")" && pwd)
DEVELOPMENT=$WORKSPACE/development-convention-plugins/plugins/development-convention/skills
TESTING=$WORKSPACE/testing-strategy-plugins/plugins/testing-strategy/skills/design-test-strategy
# 作業場所の HOME はこの script でも差し替わっているので、手元の module cache は利用者の本来の HOME から求める。
HOST_MODCACHE=$(HOME=$(eval echo "~$(id -un)") go env GOMODCACHE)

for skill in "$DEVELOPMENT/develop-inside-out" "$DEVELOPMENT/apply-layer-convention" "$DEVELOPMENT/write-readable-code" "$DEVELOPMENT/apply-yagni" "$TESTING"; do
  [ -f "$skill/SKILL.md" ] || { echo "兄弟 checkout の skill が無い: $skill" >&2; exit 2; }
done

mkdir -p out harness
cp -R "$EVALS_DIR/go-module/." out/
mkdir -p "out/docs/$BUSINESS"
cp "$TOPIC_DIR/materials/input/$BUSINESS/"*.md "out/docs/$BUSINESS/"
[ -z "$FIXTURE" ] || cp -R "$FIXTURE/." out/
for name in develop-inside-out apply-layer-convention write-readable-code apply-yagni; do
  cp -R "$DEVELOPMENT/$name" "harness/$name"
done
cp -R "$TESTING" harness/design-test-strategy

# 作業場所の HOME の go env に、手元の module cache を読むだけの proxy を書く。
GOENV_FILE="$HOME/Library/Application Support/go/env"
mkdir -p "$(dirname "$GOENV_FILE")"
printf 'GOPROXY=file://%s/cache/download\nGOSUMDB=off\nGOTOOLCHAIN=auto\n' "$HOST_MODCACHE" > "$GOENV_FILE"
(cd out && go mod download && go build ./... && go tool golangci-lint version >/dev/null)

git -C out init -q
git -C out add -A
git -C out -c user.name=eval -c user.email=eval@example.invalid commit -q -m "作業の前の状態"
