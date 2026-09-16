#!/usr/bin/env bash
# Scenario: go-conventionが18の自己完結skill（規約14＋層ごとのTDD入口4）を直接配布でき、テストの形の例がコンパイルして通る
# Given: 両runtimeのmarketplaceと同一のmanifest、直接公開する18のskill（skills/<name>）、
#        各skillのreference、check-cases.py、tests/examplesのGoモジュールがある
# When: root契約（package境界・内部skillの自己完結）、identity、入口と内部skillの対応、reference到達性、例と断片の一致、
#       check-cases.pyの正常系・正例・負例、develop-<layer>のTDD工程順、shell構文、goのgofmt・vet・shuffleテストを実行する
# Then: 不整合が一つでもあれば非0で終了する。兄弟checkout harness-tools が無ければ止まる。goが無ければgofmt・vet・testは省略と表示し失敗にしない
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PLUGIN="$ROOT/plugins/go-convention"
SKILL="$PLUGIN/skills/apply-go-test-convention"
EXAMPLES="$ROOT/tests/examples"
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/go-convention-validation.XXXXXX") || exit 2
trap 'rm -rf "$TMP_ROOT"' EXIT
passed=0 failed=0 skipped=0
pass() { printf 'PASS: %s\n' "$1"; passed=$((passed + 1)); }
fail() { printf 'FAIL: %s\n' "$1"; failed=$((failed + 1)); }
skip() { printf 'SKIP: %s\n' "$1"; skipped=$((skipped + 1)); }
skill_name() {
  python3 - "$1" <<'PY' | yq -er '.name'
from pathlib import Path
import sys

lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
if not lines or lines[0] != "---":
    raise SystemExit(2)
try:
    end = lines.index("---", 1)
except ValueError:
    raise SystemExit(2)
print("\n".join(lines[1:end]))
PY
}

for cmd in bash find jq python3 rg; do
  command -v "$cmd" >/dev/null 2>&1 && pass "command $cmd" || fail "command $cmd が無い"
done

# root契約の正本は兄弟checkout harness-tools だけ。無ければ止まる（省略もfixtureによる代用もしない）。
TOOLS="$ROOT/../harness-tools/tools"
[ -d "$TOOLS" ] || { echo "[error] 兄弟 checkout harness-tools が無い: $TOOLS" >&2; exit 2; }
python3 "$TOOLS/validate-plugin-repository.py" "$ROOT" >"$TMP_ROOT/root-contract.out" 2>&1 && pass "root契約（package境界・内部skillの自己完結）" || { cat "$TMP_ROOT/root-contract.out"; fail "root契約（package境界・内部skillの自己完結）"; }

VERSION=$(jq -er '.version' "$PLUGIN/.claude-plugin/plugin.json") || VERSION=""
if [ -n "$VERSION" ] \
  && jq -e --arg v "$VERSION" '.name=="go-convention" and (.plugins|length==1) and .plugins[0].name=="go-convention" and .plugins[0].version==$v and .plugins[0].source.path=="./plugins/go-convention"' "$ROOT/.agents/plugins/marketplace.json" >/dev/null \
  && jq -e --arg v "$VERSION" '.name=="go-convention" and (.plugins|length==1) and .plugins[0].name=="go-convention" and .plugins[0].version==$v and .plugins[0].source=="./plugins/go-convention"' "$ROOT/.claude-plugin/marketplace.json" >/dev/null; then
  pass "marketplace identity（go-convention ${VERSION}）"
else
  fail "marketplace identity"
fi

if cmp -s "$PLUGIN/.claude-plugin/plugin.json" "$PLUGIN/.codex-plugin/plugin.json" \
  && jq -e '.name=="go-convention" and (.metadata.harness|has("playbooks")|not) and (.metadata.harness|has("internalPlugins")|not) and (.skills|length)==18 and all(.skills[]; startswith("./skills/"))' "$PLUGIN/.claude-plugin/plugin.json" >/dev/null; then
  pass "runtime manifestが同一で、18の自己完結skillを直接宣言"
else
  fail "runtime manifestの同一性または入口の宣言"
fi

if PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/scripts/validate_skill_playbooks.py" "$PLUGIN" --self-test; then
  pass "18公開skillのplaybook.yml v2工程順序契約"
else
  fail "18公開skillのplaybook.yml v2工程順序契約"
fi

entry_failed=0
while IFS= read -r name; do
  entry="$PLUGIN/skills/$name"
  for f in "$entry/SKILL.md"; do
    [ -f "$f" ] || { echo "無い: $f"; entry_failed=1; }
  done
  [ "$(skill_name "$entry/SKILL.md" 2>/dev/null)" = "$name" ] || { echo "SKILL.md frontmatter nameがdirectoryと一致しない: $name"; entry_failed=1; }
done < <(jq -r '.skills[] | split("/")[-1]' "$PLUGIN/.claude-plugin/plugin.json")
[ "$(find "$PLUGIN/skills" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" = "18" ] || { echo "公開skillのdirectoryが18でない"; entry_failed=1; }
[ "$entry_failed" -eq 0 ] && pass "18の自己完結skillを直接公開" || fail "直接公開skillの対応"

FRONTMATTER_CASES="$TMP_ROOT/frontmatter-cases"
mkdir -p "$FRONTMATTER_CASES"
printf '%s\n' '---' 'name: write-go-code # 公開identity' 'description: comment付き' '---' '# 本文' >"$FRONTMATTER_CASES/comment.md"
printf '%s\n' '---' 'name: "write-go-code"' 'description: quoted' '---' '# 本文' >"$FRONTMATTER_CASES/quoted.md"
printf '%s\n' '---' 'description: 本文だけにname' '---' '# 本文' 'name: write-go-code' >"$FRONTMATTER_CASES/body-only.md"
printf '%s\n' '---' 'description: nameなし' '---' '# 本文' >"$FRONTMATTER_CASES/missing.md"
[ "$(skill_name "$FRONTMATTER_CASES/comment.md" 2>/dev/null)" = "write-go-code" ] && pass "frontmatter nameのYAML commentを受理" || fail "frontmatter nameのYAML comment"
[ "$(skill_name "$FRONTMATTER_CASES/quoted.md" 2>/dev/null)" = "write-go-code" ] && pass "frontmatter nameのquoted scalarを受理" || fail "frontmatter nameのquoted scalar"
skill_name "$FRONTMATTER_CASES/body-only.md" >/dev/null 2>&1 && fail "本文だけの偽nameを受理" || pass "本文だけの偽nameを拒否"
skill_name "$FRONTMATTER_CASES/missing.md" >/dev/null 2>&1 && fail "frontmatter name欠落を受理" || pass "frontmatter name欠落を拒否"

# 全内部skill: SKILL.md から references を全部直接リンクし、reference 間のリンク先が在る
if python3 - "$PLUGIN/skills" <<'PY2'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
bad = []
for skill in sorted(p for p in root.iterdir() if p.is_dir()):
    text = (skill / "SKILL.md").read_text()
    links = set(re.findall(r"\]\((references/[^)#]+\.md)(?:#[^)]*)?\)", text))
    refs = skill / "references"
    expected = {f"references/{p.name}" for p in refs.glob("*.md")} if refs.is_dir() else set()
    if links != expected:
        bad.append(f"{skill.name}: SKILL.mdのリンク {sorted(links)} と references {sorted(expected)} が一致しない")
    for doc in sorted(refs.glob("*.md")) if refs.is_dir() else []:
        for link in re.findall(r"\]\(([^)#]+\.md)(?:#[^)]*)?\)", doc.read_text()):
            if link.startswith(("http://", "https://")):
                continue
            if not (refs / link).is_file() and not (skill / link).is_file():
                bad.append(f"{skill.name}/references/{doc.name}: リンク先が無い {link}")
if bad:
    print("\n".join(bad))
    raise SystemExit(1)
PY2
then
  pass "全内部skillのreferenceが入口から直接到達し、reference間のリンク先が在る"
else
  fail "reference到達性"
fi

if python3 - "$SKILL/references/examples.md" "$EXAMPLES" <<'PY'
from pathlib import Path
import sys

doc = Path(sys.argv[1]).read_text()
tests = sorted(Path(sys.argv[2]).glob("*/*_test.go"))
if not tests:
    raise SystemExit(1)
for path in tests:
    if "```go\n" + path.read_text() + "```" not in doc:
        print(f"examples.md に一致しない: {path}")
        raise SystemExit(1)
PY
then
  pass "examples.mdのテストコードはtests/examplesと一致"
else
  fail "examples.mdのテストコードがtests/examplesと不一致"
fi

if python3 - "$SKILL/references" "$EXAMPLES" <<'PY'
from pathlib import Path
import re
import sys

refs = Path(sys.argv[1])
sources = [p.read_text() for p in sorted(Path(sys.argv[2]).glob("*/*_test.go"))]
bad = []
for name in ("table.md", "given.md", "then.md", "case-identity.md"):
    doc = (refs / name).read_text()
    blocks = re.findall(r"```go\n(.*?)```", doc, re.S)
    if not blocks:
        bad.append(f"{name}: go ブロックが無い")
    for block in blocks:
        if not any(block in src for src in sources):
            bad.append(f"{name}: tests/examples に無い断片: {block.splitlines()[0]!r}")
if bad:
    print("\n".join(bad))
    raise SystemExit(1)
PY
then
  pass "table.md/given.md/then.md/case-identity.mdのgoブロックはtests/examplesの部分文字列"
else
  fail "table.md/given.md/then.md/case-identity.mdにtests/examplesに無いgoブロックがある"
fi

CHECK_CASES="$SKILL/scripts/check-cases.py"
if python3 "$CHECK_CASES" "$EXAMPLES" >"$TMP_ROOT/check-cases.out" 2>&1; then
  pass "check-cases.py: tests/examplesはpackage {pkg}_test、idが空でなくディレクトリ内で一意、id/name/descriptionが各1行でこの順、nameがディレクトリ内で一意、Given/When/Thenが行頭にこの順で各1回・Andは字下げ可・NOTE行は無視"
else
  cat "$TMP_ROOT/check-cases.out"; fail "check-cases.py: tests/examples"
fi

# check-cases.py の負例と正例。numseq_test.go を1点だけ変えた複製（または同じディレクトリに1ファイル足した複製）に対する終了コードと出力を見る
mutated_case() {
  local label=$1 key=$2 expect=$3 needle=${4:-} dir="$TMP_ROOT/mut-$2"
  mkdir -p "$dir"
  cp "$EXAMPLES/numseq/numseq_test.go" "$dir/numseq_test.go"
  python3 - "$dir/numseq_test.go" "$key" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
edits = {
    "dup-id": ('"b4a0f3"', '"7c2e19"'),
    "dup-name": ('"同じ値が2つあれば別の位置として組にする"', '"和が目標になる2つの位置を返す"'),
    "empty-id": ('"91d6c8"', '""'),
    "when-before-given": (
        "description: `Given: 数列 3, 3 がある\nWhen: 和が 6 になる組を探す\n",
        "description: `When: 和が 6 になる組を探す\nGiven: 数列 3, 3 がある\n",
    ),
    "when-indented": (
        "description: `Given: 数列 3, 3 がある\nWhen: 和が 6 になる組を探す\n",
        "description: `Given: 数列 3, 3 がある\n\tWhen: 和が 6 になる組を探す\n",
    ),
    "internal-package": ("package numseq_test\n", "package numseq\n"),
    "one-line-case": (
        '\t\t\tid:   "91d6c8",\n\t\t\tname: "負の値を含んでいても組を見つける",\n',
        '\t\t\tid: "91d6c8", name: "負の値を含んでいても組を見つける",\n',
    ),
    "and-after-when": (
        "When: 和が 9 になる組を探す\nThen:",
        "When: 和が 9 になる組を探す\n  And: もう一度探す\nThen:",
    ),
    # 正例。行頭の And: も Then: の後なら許す
    "and-at-line-start": (
        "Then: 位置 0 と 1 の組が返る`,\n\t\t\tvalues: []int{2, 7, 11, 15},",
        "Then: 位置 0 と 1 の組が返る\nAnd: 数列は変わらない`,\n\t\t\tvalues: []int{2, 7, 11, 15},",
    ),
    # 正例。NOTE: 行とそれに続く字下げ行は見出しに数えない（字下げした When: があっても無視する）
    "note-lines-ignored": (
        "Then: 位置 0 と 1 の組が返る`,\n\t\t\tvalues: []int{2, 7, 11, 15},",
        "Then: 位置 0 と 1 の組が返る\n  NOTE: Rule: 和が目標になる組を返す\n    When: 説明の続き\n    Reason: 2 と 7 の和が 9 のため`,\n\t\t\tvalues: []int{2, 7, 11, 15},",
    ),
    # 負例。別ファイルのテスト関数に同じ id があれば、ディレクトリ内の重複として拒む
    "dup-id-across-files": ("package numseq_test\n", "package numseq_test\n"),
    # 正例。Benchmark の本文に Test と同じ id/name があっても、Test に併合しない
    "benchmark-not-merged": (
        "\t\t\tassert.Equal(t, tt.wantHi, got.Hi())\n\t\t})\n\t}\n}\n",
        "\t\t\tassert.Equal(t, tt.wantHi, got.Hi())\n\t\t})\n\t}\n}\n"
        "\nfunc BenchmarkFindPairSummingTo(b *testing.B) {\n"
        "\tseq := numseq.NewNumberSequence([]int{2, 7, 11, 15})\n"
        "\tfixed := struct {\n\t\tid   string\n\t\tname string\n\t}{\n"
        '\t\tid:   "TC-001",\n\t\tname: "和が目標になる2つの位置を返す",\n\t}\n'
        "\t_ = fixed\n\tfor b.Loop() {\n\t\t_, _ = numseq.FindPairSummingTo(seq, 9)\n\t}\n}\n",
    ),
    # 正例。被験体の構造体リテラルの id フィールドはケースではない
    "sut-id-ignored": (
        "\t\t\tseq := numseq.NewNumberSequence(tt.values)\n",
        "\t\t\tline := struct {\n\t\t\t\tid   string\n\t\t\t\tkind int\n\t\t\t}{\n"
        '\t\t\t\tid:   "L-1",\n\t\t\t\tkind: 0,\n\t\t\t}\n\t\t\t_ = line\n'
        "\t\t\tseq := numseq.NewNumberSequence(tt.values)\n",
    ),
    # 正例。name にエスケープした引用符があってもケースとして読む
    "escaped-quote-name": (
        '"和が目標になる2つの位置を返す"',
        '"和が目標になる \\"2つ\\" の位置を返す"',
    ),
    # 正例。同じディレクトリに TestMain だけの main_test.go があっても、TestMain を Test* として扱わない
    "testmain-accepted": ("package numseq_test\n", "package numseq_test\n"),
}
old, new = edits[sys.argv[2]]
if old not in text:
    raise SystemExit(f"変更の元になる文字列が無い: {sys.argv[2]}")
path.write_text(text.replace(old, new, 1))
if sys.argv[2] == "dup-id-across-files":
    (path.parent / "other_test.go").write_text(
        "package numseq_test\n\nimport \"testing\"\n\nfunc TestOther(t *testing.T) {\n"
        "\ttests := []struct {\n\t\tid          string\n\t\tname        string\n\t\tdescription string\n\t}{\n"
        "\t\t{\n\t\t\tid:   \"7c2e19\",\n\t\t\tname: \"別のファイルの別のケース\",\n"
        "\t\t\tdescription: `Given: 何かがある\nWhen: 何かをする\nThen: 何かが返る`,\n\t\t},\n\t}\n"
        "\tfor _, tt := range tests {\n\t\tt.Run(tt.id+\" \"+tt.name, func(t *testing.T) {})\n\t}\n}\n"
    )
if sys.argv[2] == "testmain-accepted":
    (path.parent / "main_test.go").write_text(
        "package numseq_test\n\nimport (\n\t\"os\"\n\t\"testing\"\n)\n\n"
        "func TestMain(m *testing.M) {\n\tos.Exit(m.Run())\n}\n"
    )
PY
  python3 "$CHECK_CASES" "$dir" >"$dir/out" 2>&1
  local code=$?
  case "$expect" in
    reject)
      if [ "$code" -eq 0 ]; then
        fail "check-cases.py が${label}を許可"
      elif [ -n "$needle" ] && ! rg -F "$needle" "$dir/out" >/dev/null; then
        cat "$dir/out"; fail "check-cases.py が${label}を別の理由で拒否"
      else
        pass "check-cases.py が${label}を拒否"
      fi
      ;;
    accept)
      if [ "$code" -eq 0 ]; then
        pass "check-cases.py が${label}を受理"
      else
        cat "$dir/out"; fail "check-cases.py が${label}を拒否"
      fi
      ;;
  esac
}
mutated_case "id重複" dup-id reject "ディレクトリ内で重複"
mutated_case "別ファイル間のid重複" dup-id-across-files reject "ディレクトリ内で重複"
mutated_case "name重複" dup-name reject "ディレクトリ内で重複"
mutated_case "空のid" empty-id reject "id が空"
mutated_case "Given/When/Thenの逆順" when-before-given reject "行頭にこの順で各1回でない"
mutated_case "行頭にないWhen" when-indented reject "行頭にこの順で各1回でない"
mutated_case "内部パッケージ" internal-package reject "_test でない"
mutated_case "1行ケース" one-line-case reject "複数行で書く"
mutated_case "When直後のAnd" and-after-when reject "の後以外にある"
mutated_case "行頭のAnd" and-at-line-start accept
mutated_case "NOTE行に続く字下げ行（無視する）" note-lines-ignored accept
mutated_case "Testと同じidを持つBenchmark（併合しない）" benchmark-not-merged accept
mutated_case "被験体のidフィールド（ケースと見なさない）" sut-id-ignored accept
mutated_case "エスケープした引用符を含むname" escaped-quote-name accept
mutated_case "TestMainだけを持つmain_test.go（Test*として扱わない）" testmain-accepted accept

# develop-<layer>（TDDの1単位）: 同packageの公開入口を skill: で、テスト → 赤 → 実装 → 緑 → 整える の順に呼ぶ
tdd_order_check() {
  python3 - "$1" <<'PY3'
import json, subprocess, sys
from pathlib import Path

plugin = Path(sys.argv[1])
manifest = json.loads((plugin / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
public = {Path(s).name for s in manifest["skills"]}
develop = sorted(name for name in public if name.startswith("develop-"))
bad = []
if not develop:
    bad.append("develop-<layer> の入口が manifest に無い")
for name in develop:
    layer = name.removeprefix("develop-")
    raw = subprocess.run(["yq", "-o=json", "-I=0", ".", str(plugin / "skills" / name / "playbook.yml")], text=True, capture_output=True)
    if raw.returncode:
        bad.append(f"{name}: playbook.yml を読めない"); continue
    steps = json.loads(raw.stdout)["steps"]
    def index(pred):
        return next((i for i, s in enumerate(steps) if pred(s)), None)
    test_i = index(lambda s: s.get("skill") == f"test-{layer}")
    red_i = index(lambda s: s.get("id") == "run-red" and s.get("agent_work") == "invoking_agent")
    impl_i = [i for i, s in enumerate(steps) if isinstance(s.get("skill"), str) and s["skill"].startswith("implement-")]
    green_i = index(lambda s: s.get("id") == "run-green" and s.get("agent_work") == "invoking_agent")
    refactor_i = index(lambda s: s.get("skill") == "write-go-code")
    if None in (test_i, red_i, green_i, refactor_i) or not impl_i:
        bad.append(f"{name}: test-{layer} / run-red / implement-* / run-green / write-go-code の工程が揃っていない"); continue
    if not (test_i < red_i < min(impl_i) and max(impl_i) < green_i < refactor_i):
        bad.append(f"{name}: 工程順が テスト → 赤 → 実装 → 緑 → 整える でない")
    for s in steps:
        if "skill" in s and s["skill"] not in public:
            bad.append(f"{name}: skill: {s['skill']} は同packageの公開入口でない")
        if "skill" in s and s["skill"] == "apply-go-test-convention":
            bad.append(f"{name}: テストの形の共通規約は test-<layer> が土台にするので合成入口から呼ばない")
if bad:
    print("\n".join(bad)); raise SystemExit(1)
PY3
}
if tdd_order_check "$PLUGIN"; then
  pass "develop-<layer>: test-<layer> → run-red → implement-* → run-green → write-go-code の順で同package公開入口を skill: で呼ぶ"
else
  fail "develop-<layer> のTDD工程順"
fi
TDD_MUT="$TMP_ROOT/tdd-mut"
tdd_mutated() {
  local label=$1 expect=$2 py=$3
  rm -rf "$TDD_MUT"; mkdir -p "$TDD_MUT"; cp -R "$PLUGIN/." "$TDD_MUT/"
  python3 -c "$py" "$TDD_MUT/skills/develop-domain-model/playbook.yml"
  if tdd_order_check "$TDD_MUT" >/dev/null 2>&1; then
    [ "$expect" = accept ] && pass "develop-<layer> 検査が${label}を受理" || fail "develop-<layer> 検査が${label}を受理した"
  else
    [ "$expect" = reject ] && pass "develop-<layer> 検査が${label}を拒否" || fail "develop-<layer> 検査が${label}を拒否した"
  fi
}
tdd_mutated "現行の develop-domain-model（正例）" accept 'import sys'
tdd_mutated "実装工程がテスト工程より前（反例）" reject 'import sys,pathlib
p=pathlib.Path(sys.argv[1]); t=p.read_text(); a="skill: test-domain-model"; b="skill: implement-domain-model"; p.write_text(t.replace(a,"@@").replace(b,a).replace("@@",b))'
tdd_mutated "run-red 工程の欠落（反例）" reject 'import sys,pathlib
p=pathlib.Path(sys.argv[1]); t=p.read_text(); p.write_text(t.replace("id: run-red","id: run-first"))'
tdd_mutated "整える工程が緑の前（境界例: 工程は揃うが順序だけ違う）" reject 'import sys,pathlib,json,subprocess
p=pathlib.Path(sys.argv[1]); v=json.loads(subprocess.run(["yq","-o=json","-I=0",".",str(p)],text=True,capture_output=True).stdout)
s=v["steps"]; g=next(i for i,x in enumerate(s) if x["id"]=="run-green"); r=next(i for i,x in enumerate(s) if x["id"]=="refactor")
s[g],s[r]=s[r],s[g]; s[g].pop("needs",None); s[r].pop("needs",None); p.write_text(json.dumps(v,ensure_ascii=False))'
tdd_mutated "テストの形の共通規約を合成入口から呼ぶ（反例）" reject 'import sys,pathlib
p=pathlib.Path(sys.argv[1]); t=p.read_text(); p.write_text(t.replace("skill: write-go-code","skill: apply-go-test-convention"))'

syntax_failed=0
while IFS= read -r script; do bash -n "$script" || syntax_failed=1; done < <(find "$ROOT/plugins" "$ROOT/scripts" -type f -name '*.sh' | sort)
[ "$syntax_failed" -eq 0 ] && pass "shell構文" || fail "shell構文"

if command -v go >/dev/null 2>&1; then
  if [ -z "$(cd "$EXAMPLES" && gofmt -l .)" ]; then
    pass "tests/examples gofmt -l が空"
  else
    (cd "$EXAMPLES" && gofmt -l .); fail "tests/examples gofmt -l が空でない"
  fi
  if (cd "$EXAMPLES" && go vet ./... >"$TMP_ROOT/vet.out" 2>&1); then
    pass "tests/examples go vet"
  else
    cat "$TMP_ROOT/vet.out"; fail "tests/examples go vet"
  fi
  if (cd "$EXAMPLES" && go test -shuffle=on -count=1 ./... >"$TMP_ROOT/test.out" 2>&1); then
    pass "tests/examples go test -shuffle=on（テスト関数間の順序依存は見つからなかった）"
  else
    cat "$TMP_ROOT/test.out"; fail "tests/examples go test -shuffle=on"
  fi
else
  skip "go が無いため tests/examples の gofmt・vet・test を省略"
fi

printf '\nValidation: %d passed, %d failed, %d skipped\n' "$passed" "$failed" "$skipped"
[ "$failed" -eq 0 ]
