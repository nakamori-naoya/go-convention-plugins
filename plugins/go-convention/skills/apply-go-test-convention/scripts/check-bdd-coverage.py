#!/usr/bin/env python3
"""repository 全体の *_test.go と、BDD を持つ資料を突き合わせる。

判定する述語（通ったとき言えるのはこれだけ）:
  1. 引数の各資料に `### [BDD-<3桁以上の連番>] 見出し` の形の見出しが 1 つ以上あり、同じ資料の中で ID が重複しない
     （文法の持ち主は bdd-discovery-and-formulation の write-bdd。資料の種類の接頭辞を足した ID は受け入れない）
  2. `id:` の値が `BDD-` で始まるケース、または `// どのテストも担わない BDD:` の列挙を持つ *_test.go は、
     `// BDD の資料: <repository 相対の path>` の宣言をちょうど 1 つ持ち、その path は引数の資料のどれかである
  3. 宣言したファイルの `BDD-` の id と列挙の ID は、`BDD-<3桁以上の連番>` の形で、宣言した資料の見出しにある
  4. 各資料の各 BDD ID は、その資料を宣言したファイル全体を通して、`id:` の値か列挙のどちらか一方に、ちょうど 1 回現れる
  5. 列挙は 1 ファイルに 1 つで、ファイルの最後にあり、各行は `// <ID> <理由>` の形で理由が空でない
  6. `--stopped` の一覧に載せた BDD（作業を止めた BDD）は、4 の数え方から外す。一覧の各行は
     `<資料の repository 相対 path> <BDD-ID> <理由と返し先>` の形で、資料は引数の資料のどれか、ID はその資料の見出しにあり、
     理由が空でなく、一覧の中で重複せず、どのテストの `id:` にも列挙にも現れない。止めた BDD は違反とせず、一覧として出す

読み方:
  - `id:` 行をケースと見なすのは、直後の行が `name:` で始まるときだけ（被験体の構造体リテラルの id は見ない）
  - 走査するのは repository root 配下の *_test.go 全部（`.git` と `vendor` を除く）
  - 資料の path は repository root からの相対 path に正規化して比べる
  - 止めた BDD の一覧は、空行と `#` で始まる行を読まない。一覧の path は、絶対 path か repository root からの相対 path

使い方: check-bdd-coverage.py [--stopped <止めた BDD の一覧>] <repository root> <資料.md> [<資料.md> ...]
違反があれば `内容` を 1 行ずつ stdout に出して終了コード 1。
資料か一覧が無い、見出しが無い、*_test.go が 1 つも無ければ stderr に理由を出して終了コード 2。違反が無ければ終了コード 0。
止めた BDD は、違反が無くても `止めた BDD:` の行として stdout に出す。止めた範囲があっても本当の漏れと区別できるようにするためである。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^###\s+\[(BDD-\d{3,})\]\s+\S", re.M)
ID_VALUE_RE = re.compile(r"^BDD-\d{3,}$")
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


def stopped_entries(path: Path, docs: dict[str, list[str]]) -> tuple[dict[tuple[str, str], str], list[str]]:
    entries: dict[tuple[str, str], str] = {}
    problems: list[str] = []
    keys = sorted(docs, key=len, reverse=True)
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"{path.name}:{n}"
        doc = next((k for k in keys if line.startswith(k) and line[len(k):len(k) + 1].isspace()), None)
        if doc is None:
            problems.append(f"{where}: 止めた BDD の資料が引数の資料に無い（`<資料の path> <BDD-ID> <理由と返し先>` の形）")
            continue
        rest = line[len(doc):].strip().split(maxsplit=1)
        bdd_id, reason = rest[0], (rest[1].strip() if len(rest) > 1 else "")
        if not ID_VALUE_RE.match(bdd_id) or bdd_id not in docs[doc]:
            problems.append(f"{where}: {bdd_id} は資料 {doc} の見出しに無い")
            continue
        if not reason:
            problems.append(f"{where}: 止めた {bdd_id} に理由が無い")
        if (doc, bdd_id) in entries:
            problems.append(f"{where}: 止めた {bdd_id} が一覧の中で重複している")
        entries[(doc, bdd_id)] = reason
    return entries, problems


def main(argv: list[str]) -> int:
    stopped_arg = None
    if len(argv) > 2 and argv[1] == "--stopped":
        stopped_arg, argv = argv[2], [argv[0]] + argv[3:]
    if len(argv) < 3:
        print("usage: check-bdd-coverage.py [--stopped <止めた BDD の一覧>] <repository root> <資料.md> [<資料.md> ...]", file=sys.stderr)
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
            print(f"{key}: `### [BDD-<3桁以上の連番>] 見出し` の形の見出しが無い", file=sys.stderr)
            return 2
        seen: set[str] = set()
        for bdd_id in ids:
            if bdd_id in seen:
                problems.append(f"{key}: 見出しの {bdd_id} が資料の中で重複している")
            seen.add(bdd_id)
        docs[key] = ids

    stopped: dict[tuple[str, str], str] = {}
    if stopped_arg is not None:
        stopped_path = Path(stopped_arg) if Path(stopped_arg).is_absolute() else root / stopped_arg
        if not stopped_path.is_file():
            print(f"{stopped_arg}: 止めた BDD の一覧が無い", file=sys.stderr)
            return 2
        stopped, stopped_problems = stopped_entries(stopped_path, docs)
        problems.extend(stopped_problems)

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
            if not ID_VALUE_RE.match(bdd_id):
                problems.append(f"{where}: {bdd_id} は BDD-<3桁以上の連番> の形でない")
                continue
            if bdd_id not in doc_ids:
                problems.append(f"{where}: {bdd_id} は資料 {declared} の見出しに無い")
                continue
            occurrences.setdefault((declared, bdd_id), []).append(where)
        for n, bdd_id in listed:
            where = f"{name}:{n}（列挙）"
            if not ID_VALUE_RE.match(bdd_id):
                problems.append(f"{where}: {bdd_id} は BDD-<3桁以上の連番> の形でない")
                continue
            if bdd_id not in doc_ids:
                problems.append(f"{where}: {bdd_id} は資料 {declared} の見出しに無い")
                continue
            occurrences.setdefault((declared, bdd_id), []).append(where)

    counted = 0
    for doc, ids in docs.items():
        for bdd_id in ids:
            places = occurrences.get((doc, bdd_id), [])
            if (doc, bdd_id) in stopped:
                if places:
                    problems.append(f"{doc} の {bdd_id}: 止めた BDD の一覧にあるのに、テストに現れる: {', '.join(places)}")
                continue
            if not places:
                problems.append(f"{doc} の {bdd_id}: どのテストの id: にも、どのテストも担わない BDD の列挙にも無い")
            elif len(places) > 1:
                problems.append(f"{doc} の {bdd_id}: {len(places)} か所に現れる（ちょうど 1 回）: {', '.join(places)}")
            else:
                counted += 1

    for p in problems:
        print(p)
    for (doc, bdd_id), reason in stopped.items():
        print(f"止めた BDD: {doc} の {bdd_id}: {reason}")
    if problems:
        return 1
    print(f"check-bdd-coverage: 資料 {len(docs)} 本の BDD {counted} 件が、それぞれちょうど 1 回現れる。止めた BDD {len(stopped)} 件。違反なし")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
