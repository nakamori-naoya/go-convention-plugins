#!/usr/bin/env python3
"""MarkdownのGo断片を解析し、Query契約の所有と依存方向を検査する。"""
from __future__ import annotations

import argparse
import re
import shutil
import tempfile
from pathlib import Path

TYPES = ("RoomAvailability", "AvailableSlot", "ActiveSlot", "WaitingEntry", "ReservationSummary", "ReservationHistory", "HistoryEvent", "Page")
ERRORS = ("ErrNotFound", "ErrDayHasClock", "ErrPageLimitOutOfRange", "ErrPageOffsetNegative")
CONSTANTS = ("MaxPageLimit", "StatusTentative", "StatusConfirmed")
IMPORT = 'querycontract "example.com/roomflow/reservation/usecase/query"'


def go_blocks(text: str) -> list[str]:
    return re.findall(r"```go\s*\n(.*?)```", text, re.S)


def validate(root: Path) -> list[str]:
    contract_path = root / "plugins/go-convention/skills/implement-usecase/references/query.md"
    impl_paths = [
        root / "plugins/go-convention/skills/implement-query-service/SKILL.md",
        root / "plugins/go-convention/skills/implement-query-service/references/query-service.md",
        root / "plugins/go-convention/skills/implement-query-service/references/dto.md",
    ]
    contract = contract_path.read_text()
    impl_texts = [path.read_text() for path in impl_paths]
    contract_code = "\n".join(go_blocks(contract))
    impl_code = "\n".join(block for text in impl_texts for block in go_blocks(text))
    errors: list[str] = []

    if '"example.com/roomflow/query"' in contract:
        errors.append("usecase/query契約がQuery実装をimportしている")

    for name in TYPES:
        if not re.search(rf"(?m)^type\s+{name}\b", contract_code):
            errors.append(f"usecase/query契約に型が無い: {name}")
        if re.search(rf"(?m)^type\s+{name}\b", impl_code):
            errors.append(f"Query実装が公開契約型を定義している: {name}")
        bare = re.search(rf"(?<![.\w]){name}\b", impl_code)
        if bare:
            errors.append(f"Query実装が契約型をquerycontract経由で使っていない: {name}")

    for name in ERRORS:
        if not re.search(rf"(?m)^\s*(?:const\s+)?{name}\s*=", contract_code):
            errors.append(f"usecase/query契約にsentinelが無い: {name}")
        if re.search(rf"(?m)^\s*(?:const\s+)?{name}\s*=", impl_code):
            errors.append(f"Query実装が公開sentinelを定義している: {name}")
        if re.search(rf"(?<![.\w]){name}\b", impl_code):
            errors.append(f"Query実装がsentinelをquerycontract経由で使っていない: {name}")

    for name in CONSTANTS:
        if not re.search(rf"(?m)^\s*(?:const\s+)?{name}\s*=", contract_code):
            errors.append(f"usecase/query契約に定数が無い: {name}")
        if re.search(rf"(?m)^\s*(?:const\s+)?{name}\s*=", impl_code):
            errors.append(f"Query実装が公開定数を定義している: {name}")

    for path, text in zip(impl_paths, impl_texts):
        if "querycontract." in "\n".join(go_blocks(text)) and IMPORT not in text:
            errors.append(f"usecase/query契約importが無い: {path.name}")

    prose = "\n".join(impl_texts)
    forbidden = (
        r"ドメイン(?:の型)?をimportしない",
        r"ドメインを経由せず",
        r"ドメイン非経由",
        r"値オブジェクトを(?:使わ|呼ば)ない",
        r"値オブジェクトを避けるため.*(?:列|保存)",
        r"行\s*→\s*DTO\s*だけ",
        r"行型の列.*1:1",
        r"必要な値がデータモデルの列または確定済み集計から導けない",
        r"必要な列または関係集計がデータモデル資料から導けない",
    )
    for pattern in forbidden:
        if re.search(pattern, prose):
            errors.append(f"値オブジェクト・純関数まで禁じる記述: {pattern}")
    if "値オブジェクトまたは純関数を再利用" not in prose:
        errors.append("SQLに不向きな業務計算で値オブジェクト・純関数を再利用する規則が無い")
    if not re.search(r"集約・エンティティ.*復元", prose):
        errors.append("集約・エンティティの復元禁止が無い")
    return errors


def self_test(root: Path) -> list[str]:
    failures: list[str] = []
    mutations = {
        "ActiveSlot": "```go\ntype ActiveSlot struct{}\n```\n",
        "Page": "```go\ntype Page struct{}\n```\n",
        "ErrNotFound": "```go\nvar ErrNotFound = errors.New(\"x\")\n```\n",
        "RoomAvailability": "```go\ntype RoomAvailability struct{}\n```\n",
        "VO全面禁止": "ドメインをimportしない。値オブジェクトを使わない。\n",
    }
    with tempfile.TemporaryDirectory(prefix="query-dependency-") as tmp:
        for name, addition in mutations.items():
            target = Path(tmp) / name
            shutil.copytree(root, target)
            path = target / "plugins/go-convention/skills/implement-query-service/references/dto.md"
            path.write_text(path.read_text() + "\n" + addition)
            if not validate(target):
                failures.append(f"mutationを拒否できない: {name}")
        target = Path(tmp) / "missing-import"
        shutil.copytree(root, target)
        path = target / "plugins/go-convention/skills/implement-query-service/references/dto.md"
        path.write_text(path.read_text().replace(IMPORT, ""))
        if not validate(target):
            failures.append("mutationを拒否できない: usecase/query import欠落")
        target = Path(tmp) / "old-skill-blanket"
        shutil.copytree(root, target)
        path = target / "plugins/go-convention/skills/implement-query-service/SKILL.md"
        path.write_text(path.read_text() + "\nドメインを経由せず、行 → DTO だけにする。\n")
        if not validate(target):
            failures.append("mutationを拒否できない: SKILLの旧全面禁止")
        target = Path(tmp) / "old-narrow-stop"
        shutil.copytree(root, target)
        path = target / "plugins/go-convention/skills/implement-query-service/references/dto.md"
        path.write_text(path.read_text() + "\n必要な値がデータモデルの列または確定済み集計から導けない場合は停止する。\n")
        if not validate(target):
            failures.append("mutationを拒否できない: 狭い導出停止条件")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    errors = validate(args.root)
    if args.self_test:
        errors.extend(self_test(args.root))
    if errors:
        print("\n".join(errors))
        return 1
    print("Query依存方向と契約所有: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
