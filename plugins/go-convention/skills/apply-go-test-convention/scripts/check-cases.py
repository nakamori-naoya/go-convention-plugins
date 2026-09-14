#!/usr/bin/env python3
"""ディレクトリ配下の *_test.go を走査し、ケースの識別に関する述語を判定する。

判定する述語（通ったとき言えるのはこれだけ）:
  1. package 行が `{pkg}_test` である
  2. `func Test*`（`TestMain` を除く）ごとに、`id:` 行が1つ以上あり、値は空でなく、同じディレクトリの `*_test.go` 全体で重複しない
  3. `id:` / `name:` / `description:` は各1行で始まり、この順に隣接する
  4. `name:` の値が同じディレクトリの `*_test.go` 全体で重複しない
  5. `description:` は raw string で、`Given:` / `When:` / `Then:` を行頭にこの順で各1回持ち、
     `And:` は行頭または字下げで `Given:` か `Then:`（またはその `And:`）の後にだけ現れ、
     `NOTE:` で始まる行とそれに続く字下げ行は無視する

読み方:
  - 本文は `^func ` で切り、名前が `Test` で始まる関数だけを見る（`Benchmark*` は見ない）。
    `TestMain` はテスト関数ではないので見ない（`main_test.go` の `TestMain` だけのファイルは受理する）
  - `id:` 行をケースと見なすのは、直後の行が `name:` のときと、同じ行に `name:` があるときだけ。
    被験体の構造体リテラルにある `id` フィールドは見ない
  - 一意の範囲は `*_test.go` があるディレクトリ（サブディレクトリは別のディレクトリ）

使い方: check-cases.py <dir>
違反があれば `path:line: 内容` を出力して終了コード 1。*_test.go が無ければ 2。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

STR = r'"((?:[^"\\]|\\.)*)"'
ID_RE = re.compile(r"^\s*id:\s*" + STR + r"\s*,\s*$")
LOOSE_ID_RE = re.compile(r"^\s*\{?\s*id:\s*" + STR)
NAME_RE = re.compile(r"^\s*name:\s*" + STR + r"\s*,\s*$")
INLINE_NAME_RE = re.compile(r"\bname:\s*\"")
DESC_START_RE = re.compile(r"^\s*description:\s*`")
FUNC_RE = re.compile(r"^func ", re.M)
TEST_NAME_RE = re.compile(r"^func (Test\w*)\(")
PACKAGE_RE = re.compile(r"^package (\w+)$", re.M)
HEAD_RE = re.compile(r"^(Given|When|Then):")
AND_RE = re.compile(r"^\s*And:")
NOTE_RE = re.compile(r"^\s*NOTE:")


def split_test_functions(text: str) -> list[tuple[str, int, str]]:
    """(関数名, 開始行番号, 本文) の並び。本文は次のトップレベル func まで。Test* だけ返す（TestMain は返さない）。"""
    marks = [m.start() for m in FUNC_RE.finditer(text)]
    out = []
    for i, start in enumerate(marks):
        end = marks[i + 1] if i + 1 < len(marks) else len(text)
        body = text[start:end]
        m = TEST_NAME_RE.match(body)
        if not m or m.group(1) == "TestMain":
            continue
        out.append((m.group(1), text.count("\n", 0, start) + 1, body))
    return out


def is_case_id_line(lines: list[str], i: int) -> bool:
    """`id:` 行がケースの識別か。直後の行が `name:` か、同じ行に `name:` があれば識別。"""
    m = LOOSE_ID_RE.match(lines[i])
    if not m:
        return False
    next_is_name = i + 1 < len(lines) and NAME_RE.match(lines[i + 1]) is not None
    inline_name = INLINE_NAME_RE.search(lines[i], m.end()) is not None
    return next_is_name or inline_name


def description_heads(desc: str) -> list[str]:
    """description の見出し語の並び。NOTE: 行とそれに続く字下げ行は含めない。"""
    heads: list[str] = []
    in_note = False
    for line in desc.splitlines():
        if in_note and line[:1].isspace():
            continue
        in_note = False
        if NOTE_RE.match(line):
            in_note = True
            continue
        if m := HEAD_RE.match(line):
            heads.append(m.group(1))
        elif AND_RE.match(line):
            heads.append("And")
    return heads


def description_violations(desc: str) -> list[str]:
    heads = description_heads(desc)
    problems = []
    if [h for h in heads if h != "And"] != ["Given", "When", "Then"]:
        problems.append("Given:/When:/Then: が行頭にこの順で各1回でない")
    for i, h in enumerate(heads):
        if h == "And" and (i == 0 or heads[i - 1] == "When"):
            problems.append("And: が Given:/Then:（またはその And:）の後以外にある")
            break
    return problems


def check_function(
    path: Path,
    fn_name: str,
    fn_line: int,
    body: str,
    seen_ids: dict[str, str],
    seen_names: dict[str, str],
) -> list[str]:
    problems = []
    lines = body.splitlines()
    found = False
    for i, line in enumerate(lines):
        if not is_case_id_line(lines, i):
            continue
        found = True
        lineno = fn_line + i
        m = ID_RE.match(line)
        if not m:
            problems.append(f"{path}:{lineno}: id: の行に他のフィールドがある（1ケースは複数行で書く）")
            continue
        value = m.group(1)
        where = f"{path}:{lineno}"
        if value == "":
            problems.append(f"{where}: id が空")
        elif value in seen_ids:
            problems.append(f"{where}: id {value!r} がディレクトリ内で重複（初出 {seen_ids[value]}）")
        else:
            seen_ids[value] = where
        nm = NAME_RE.match(lines[i + 1]) if i + 1 < len(lines) else None
        if not nm:
            problems.append(f"{where}: id の直後の行が name: でない")
            continue
        name = nm.group(1)
        name_where = f"{path}:{lineno + 1}"
        if name in seen_names:
            problems.append(f"{name_where}: name {name!r} がディレクトリ内で重複（初出 {seen_names[name]}）")
        else:
            seen_names[name] = name_where
        if i + 2 >= len(lines) or not DESC_START_RE.match(lines[i + 2]):
            problems.append(f"{where}: name の直後の行が description: でない")
            continue
        rest = "\n".join(lines[i + 2 :])
        raw = rest.split("`", 2)
        if len(raw) < 3:
            problems.append(f"{path}:{lineno + 2}: description の raw string が閉じていない")
            continue
        for p in description_violations(raw[1]):
            problems.append(f"{path}:{lineno + 2}: {p}")
    if not found:
        problems.append(f"{path}:{fn_line}: {fn_name} に id: の行が無い")
    return problems


def check_file(path: Path, seen_ids: dict[str, str], seen_names: dict[str, str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems = []
    pkg = PACKAGE_RE.search(text)
    if not pkg or not pkg.group(1).endswith("_test"):
        problems.append(f"{path}:1: package が {{pkg}}_test でない")
    for fn_name, fn_line, body in split_test_functions(text):
        problems.extend(check_function(path, fn_name, fn_line, body, seen_ids, seen_names))
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check-cases.py <dir>", file=sys.stderr)
        return 2
    root = Path(argv[1])
    files = sorted(p for p in root.rglob("*_test.go") if p.is_file())
    if not files:
        print(f"{root}: *_test.go が無い", file=sys.stderr)
        return 2
    problems = []
    by_dir: dict[Path, tuple[dict[str, str], dict[str, str]]] = {}
    for f in files:
        seen_ids, seen_names = by_dir.setdefault(f.parent, ({}, {}))
        problems.extend(check_file(f, seen_ids, seen_names))
    for p in problems:
        print(p)
    if problems:
        return 1
    print(f"check-cases: {len(files)} files, 違反なし")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
