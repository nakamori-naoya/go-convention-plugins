#!/usr/bin/env python3
"""資料の BDD ID と、ディレクトリの *_test.go の id: ・末尾コメントを突き合わせる。

判定する述語（通ったとき言えるのはこれだけ）:
  1. 資料に `### [BDD-NNN] 見出し` の形の見出しが 1 つ以上ある
  2. 資料の各 BDD ID が、ディレクトリの `*_test.go` の `id:` の値か、
     `// テストしない BDD:` に続く `// BDD-NNN 理由` のどちらか一方に現れる（両方には現れない）
  3. `id:` の値のうち `BDD-` で始まるものは、資料の見出しにある
  4. `// テストしない BDD:` の列挙は 1 ファイルに 1 つで、ファイルの最後にあり、各行は `// BDD-NNN 理由` の形で理由が空でない

読み方:
  - `id:` 行をケースと見なすのは、直後の行が `name:` で始まるときだけ（被験体の構造体リテラルの id は見ない）
  - ディレクトリは再帰しない（Go の package 1 つ）。末尾コメントの後に許すのはコメント行と空行だけ

使い方: check-bdd-coverage.py <資料.md> <テストのあるディレクトリ>
違反があれば `内容` を出力して終了コード 1。資料に見出しが無い、または *_test.go が無ければ 2。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^###\s+\[(BDD-\d+)\]\s+\S", re.M)
ID_RE = re.compile(r'^\s*id:\s*"((?:[^"\\]|\\.)*)"\s*,\s*$')
NAME_RE = re.compile(r'^\s*name:\s*"')
UNTESTED_HEAD_RE = re.compile(r"^//\s*テストしない BDD:\s*$")
UNTESTED_LINE_RE = re.compile(r"^//\s*(BDD-\d+)(?:\s+(.*))?$")
COMMENT_OR_BLANK_RE = re.compile(r"^(//.*)?$")


def doc_ids(doc: Path) -> list[str]:
    return HEADING_RE.findall(doc.read_text(encoding="utf-8"))


def case_ids(lines: list[str]) -> list[str]:
    out = []
    for i, line in enumerate(lines):
        m = ID_RE.match(line)
        if m and i + 1 < len(lines) and NAME_RE.match(lines[i + 1]):
            out.append(m.group(1))
    return out


def untested(path: Path, lines: list[str]) -> tuple[dict[str, str], list[str]]:
    """末尾コメントの {ID: 理由} と、その形の違反。"""
    heads = [i for i, line in enumerate(lines) if UNTESTED_HEAD_RE.match(line.strip())]
    if not heads:
        return {}, []
    problems = []
    if len(heads) > 1:
        problems.append(f"{path}:{heads[1] + 1}: `// テストしない BDD:` が 2 つ以上ある（1 ファイルに 1 つ）")
    start = heads[0]
    found: dict[str, str] = {}
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if not COMMENT_OR_BLANK_RE.match(stripped):
            problems.append(f"{path}:{i + 1}: `// テストしない BDD:` の後にコメントでも空行でもない行がある（列挙はファイルの最後に置く）")
            break
        m = UNTESTED_LINE_RE.match(stripped)
        if not m:
            if stripped:
                problems.append(f"{path}:{i + 1}: 末尾コメントの行が `// BDD-NNN 理由` の形でない")
            continue
        bdd_id, reason = m.group(1), (m.group(2) or "").strip()
        if not reason:
            problems.append(f"{path}:{i + 1}: {bdd_id} に理由が無い")
        found[bdd_id] = reason
    return found, problems


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: check-bdd-coverage.py <資料.md> <dir>", file=sys.stderr)
        return 2
    doc, root = Path(argv[1]), Path(argv[2])
    if not doc.is_file():
        print(f"{doc}: 資料が無い", file=sys.stderr)
        return 2
    ids = doc_ids(doc)
    if not ids:
        print(f"{doc}: `### [BDD-NNN] 見出し` の形の見出しが無い", file=sys.stderr)
        return 2
    files = sorted(p for p in root.glob("*_test.go") if p.is_file())
    if not files:
        print(f"{root}: *_test.go が無い", file=sys.stderr)
        return 2

    problems: list[str] = []
    tested: dict[str, str] = {}
    listed: dict[str, str] = {}
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        for value in case_ids(lines):
            if value.startswith("BDD-"):
                tested.setdefault(value, str(path))
        found, form_problems = untested(path, lines)
        problems.extend(form_problems)
        for bdd_id in found:
            listed.setdefault(bdd_id, str(path))

    doc_set = set(ids)
    for bdd_id in ids:
        in_test, in_list = bdd_id in tested, bdd_id in listed
        if in_test and in_list:
            problems.append(f"{bdd_id}: id: （{tested[bdd_id]}）と末尾コメント（{listed[bdd_id]}）の両方に現れる")
        elif not in_test and not in_list:
            problems.append(f"{bdd_id}: 資料 {doc} にあるが、id: にも末尾コメントにも無い")
    for bdd_id, where in sorted(tested.items()):
        if bdd_id not in doc_set:
            problems.append(f"{where}: id {bdd_id!r} は資料 {doc} の見出しに無い")
    for bdd_id, where in sorted(listed.items()):
        if bdd_id not in doc_set:
            problems.append(f"{where}: 末尾コメントの {bdd_id} は資料 {doc} の見出しに無い")

    for p in problems:
        print(p)
    if problems:
        return 1
    print(
        f"check-bdd-coverage: 資料の BDD {len(ids)} 件（id: {len(tested)} 件 / 末尾コメント {len(listed)} 件）、違反なし"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
