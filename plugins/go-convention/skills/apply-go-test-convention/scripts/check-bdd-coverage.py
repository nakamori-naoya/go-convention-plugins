#!/usr/bin/env python3
"""repository 全体の *_test.go と、BDD を持つ資料を突き合わせる。

判定する述語（通ったとき言えるのはこれだけ）:
  1. 引数の各資料に `### [BDD-…] 見出し` の形の見出しが 1 つ以上あり、同じ資料の中で ID が重複しない
  2. `id:` の値が `BDD-` で始まるケース、または `// どのテストも担わない BDD:` の列挙を持つ *_test.go は、
     `// BDD の資料: <repository 相対の path>` の宣言をちょうど 1 つ持ち、その path は引数の資料のどれかである
  3. 宣言したファイルの `BDD-` の id と列挙の ID は、宣言した資料の見出しにある
  4. 各資料の各 BDD ID は、その資料を宣言したファイル全体を通して、`id:` の値か列挙のどちらか一方に、ちょうど 1 回現れる
  5. 列挙は 1 ファイルに 1 つで、ファイルの最後にあり、各行は `// <ID> <理由>` の形で理由が空でない

読み方:
  - `id:` 行をケースと見なすのは、直後の行が `name:` で始まるときだけ（被験体の構造体リテラルの id は見ない）
  - 走査するのは repository root 配下の *_test.go 全部（`.git` と `vendor` を除く）
  - 資料の path は repository root からの相対 path に正規化して比べる

使い方: check-bdd-coverage.py <repository root> <資料.md> [<資料.md> ...]
違反があれば `内容` を 1 行ずつ stdout に出して終了コード 1。
資料が無い、見出しが無い、*_test.go が 1 つも無ければ stderr に理由を出して終了コード 2。違反が無ければ終了コード 0。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^###\s+\[(BDD-[^\]\s]+)\]\s+\S", re.M)
ID_RE = re.compile(r'^\s*id:\s*"((?:[^"\\]|\\.)*)"\s*,\s*$')
NAME_RE = re.compile(r"^\s*name:\s*\"")
DECL_RE = re.compile(r"^//\s*BDD の資料:\s*(\S.*?)\s*$")
UNOWNED_HEAD_RE = re.compile(r"^//\s*どのテストも担わない BDD:\s*$")
UNOWNED_LINE_RE = re.compile(r"^//\s*(BDD-\S+)(?:\s+(.*))?$")
COMMENT_OR_BLANK_RE = re.compile(r"^(//.*)?$")
SKIP_DIRS = {".git", "vendor"}


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def test_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*_test.go")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_file():
            out.append(p)
    return out


def case_ids(lines: list[str]) -> list[tuple[int, str]]:
    out = []
    for i, line in enumerate(lines):
        m = ID_RE.match(line)
        if m and i + 1 < len(lines) and NAME_RE.match(lines[i + 1]):
            out.append((i + 1, m.group(1)))
    return out


def unowned(path: str, lines: list[str]) -> tuple[list[tuple[int, str]], list[str]]:
    heads = [i for i, line in enumerate(lines) if UNOWNED_HEAD_RE.match(line.strip())]
    if not heads:
        return [], []
    problems = []
    if len(heads) > 1:
        problems.append(f"{path}:{heads[1] + 1}: `// どのテストも担わない BDD:` が 2 つ以上ある（1 ファイルに 1 つ）")
    found = []
    for i in range(heads[0] + 1, len(lines)):
        stripped = lines[i].strip()
        if not COMMENT_OR_BLANK_RE.match(stripped):
            problems.append(f"{path}:{i + 1}: 列挙の後にコメントでも空行でもない行がある（列挙はファイルの最後に置く）")
            break
        if not stripped:
            continue
        m = UNOWNED_LINE_RE.match(stripped)
        if not m:
            problems.append(f"{path}:{i + 1}: 列挙の行が `// <ID> <理由>` の形でない")
            continue
        if not (m.group(2) or "").strip():
            problems.append(f"{path}:{i + 1}: {m.group(1)} に理由が無い")
        found.append((i + 1, m.group(1)))
    return found, problems


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: check-bdd-coverage.py <repository root> <資料.md> [<資料.md> ...]", file=sys.stderr)
        return 2
    root = Path(argv[1])
    if not root.is_dir():
        print(f"{root}: repository root が無い", file=sys.stderr)
        return 2

    problems: list[str] = []
    docs: dict[str, list[str]] = {}
    for arg in argv[2:]:
        doc = Path(arg) if Path(arg).is_absolute() else root / arg
        if not doc.is_file():
            print(f"{arg}: 資料が無い", file=sys.stderr)
            return 2
        key = rel(root, doc)
        ids = HEADING_RE.findall(doc.read_text(encoding="utf-8"))
        if not ids:
            print(f"{key}: `### [BDD-…] 見出し` の形の見出しが無い", file=sys.stderr)
            return 2
        seen: set[str] = set()
        for bdd_id in ids:
            if bdd_id in seen:
                problems.append(f"{key}: 見出しの {bdd_id} が資料の中で重複している")
            seen.add(bdd_id)
        docs[key] = ids

    files = test_files(root)
    if not files:
        print(f"{root}: *_test.go が無い", file=sys.stderr)
        return 2

    occurrences: dict[tuple[str, str], list[str]] = {}
    for path in files:
        name = rel(root, path)
        lines = path.read_text(encoding="utf-8").splitlines()
        bdd_cases = [(n, v) for n, v in case_ids(lines) if v.startswith("BDD-")]
        listed, form_problems = unowned(name, lines)
        problems.extend(form_problems)
        if not bdd_cases and not listed:
            continue
        decls = [(i + 1, m.group(1)) for i, line in enumerate(lines) if (m := DECL_RE.match(line.strip()))]
        if len(decls) != 1:
            problems.append(f"{name}: BDD の id か列挙を持つのに、`// BDD の資料:` の宣言が {len(decls)} 個ある（ちょうど 1 つ）")
            continue
        line_no, declared = decls[0]
        declared = Path(declared).as_posix()
        if declared not in docs:
            problems.append(f"{name}:{line_no}: 宣言した資料 {declared} が引数の資料に無い")
            continue
        doc_ids = set(docs[declared])
        for n, bdd_id in bdd_cases:
            where = f"{name}:{n}（id:）"
            if bdd_id not in doc_ids:
                problems.append(f"{where}: {bdd_id} は資料 {declared} の見出しに無い")
                continue
            occurrences.setdefault((declared, bdd_id), []).append(where)
        for n, bdd_id in listed:
            where = f"{name}:{n}（列挙）"
            if bdd_id not in doc_ids:
                problems.append(f"{where}: {bdd_id} は資料 {declared} の見出しに無い")
                continue
            occurrences.setdefault((declared, bdd_id), []).append(where)

    counted = 0
    for doc, ids in docs.items():
        for bdd_id in ids:
            places = occurrences.get((doc, bdd_id), [])
            if not places:
                problems.append(f"{doc} の {bdd_id}: どのテストの id: にも、どのテストも担わない BDD の列挙にも無い")
            elif len(places) > 1:
                problems.append(f"{doc} の {bdd_id}: {len(places)} か所に現れる（ちょうど 1 回）: {', '.join(places)}")
            else:
                counted += 1

    for p in problems:
        print(p)
    if problems:
        return 1
    print(f"check-bdd-coverage: 資料 {len(docs)} 本の BDD {counted} 件が、それぞれちょうど 1 回現れる。違反なし")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
