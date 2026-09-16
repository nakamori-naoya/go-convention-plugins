#!/usr/bin/env python3
"""直接公開skillに隣接するplaybook.yml v2の工程順序契約を検査する。"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit


class WorkflowError(ValueError):
    pass


def fail(message: str) -> None:
    raise WorkflowError(message)


def load_yaml(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        fail(f"playbook.ymlがregular fileではありません: {path}")
    result = subprocess.run(
        ["yq", "-o=json", "-I=0", ".", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        fail(f"playbook.ymlをYAMLとして解析できません: {path}: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"playbook.ymlのparser出力が不正です: {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"playbook.ymlがobjectではありません: {path}")
    return value


def names(value: object, label: str, *, empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not empty and not value):
        fail(f"{label}が文字列配列ではありません")
    if any(not isinstance(item, str) or not item for item in value):
        fail(f"{label}に空または文字列以外の値があります")
    result = list(value)
    if len(result) != len(set(result)):
        fail(f"{label}に重複があります")
    return result


def markdown_link_targets(text: str) -> list[str]:
    """Markdownのinline linkとfull/collapsed/shortcut reference linkから宛先を取り出す。"""
    def normalize_label(label: str) -> str:
        return " ".join(label.split()).casefold()

    inline = re.compile(
        r"\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)\n]+))"
        r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^\)\n]*\)))?\s*\)"
    )
    definitions = {
        normalize_label(match.group(1)): match.group(2) or match.group(3)
        for match in re.finditer(
            r"(?m)^\s*\[([^\]\n]+)\]:\s*(?:<([^>\n]+)>|([^\s\n]+))",
            text,
        )
    }
    targets = [match.group(1) or match.group(2) for match in inline.finditer(text)]
    for match in re.finditer(r"\[[^\]\n]+\]\[([^\]\n]+)\]", text):
        target = definitions.get(normalize_label(match.group(1)))
        if target is not None:
            targets.append(target)
    for match in re.finditer(r"(?<!!)\[([^\]\n]+)\]\[\]", text):
        target = definitions.get(normalize_label(match.group(1)))
        if target is not None:
            targets.append(target)
    for match in re.finditer(r"(?m)(?<![!\]])\[([^\]\n]+)\](?![ \t]*(?:\(|\[|:))", text):
        target = definitions.get(normalize_label(match.group(1)))
        if target is not None:
            targets.append(target)
    return targets


def links_to_adjacent_playbook(entry: Path) -> bool:
    expected = (entry.parent / "playbook.yml").resolve()
    for target in markdown_link_targets(entry.read_text(encoding="utf-8")):
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        if (entry.parent / unquote(parsed.path)).resolve() == expected:
            return True
    return False


def mappings(value: object, label: str) -> list[dict]:
    if not isinstance(value, list):
        fail(f"{label}がmapping配列ではありません")
    if any(not isinstance(item, dict) for item in value):
        fail(f"{label}にmapping以外の値があります")
    return list(value)


def validate_playbook(skill_root: Path, identity: str, public_skills: set[str]) -> None:
    entry = skill_root / "SKILL.md"
    if entry.is_symlink() or not entry.is_file():
        fail(f"SKILL.mdがregular fileではありません: {entry}")
    if not links_to_adjacent_playbook(entry):
        fail(f"公開SKILL.mdが隣接playbook.ymlへ接続していません: {entry}")
    value = load_yaml(skill_root / "playbook.yml")
    required = {"version", "name", "steps"}
    if not required <= set(value):
        fail(f"playbook.ymlにversion、name、stepsが揃っていません: {skill_root}")
    if value["version"] != 2 or value["name"] != identity:
        fail(f"playbook.ymlのversionまたはnameが不一致です: {skill_root}")
    if "description" in value and (not isinstance(value["description"], str) or not value["description"]):
        fail(f"playbook.ymlのdescriptionがありません: {skill_root}")
    available = set(names(value.get("inputs", []), f"{identity}.inputs", empty=True))
    directive = value.get("instructions", {}).get("execution", {}).get("directive")
    if "instructions" in value and (not isinstance(directive, str) or not directive):
        fail(f"playbook.ymlに実行directiveがありません: {skill_root}")
    external: set[str] = set()
    for dependency in mappings(value.get("requires", []), f"{identity}.requires"):
        if set(dependency) != {"plugin", "marketplace"}:
            fail(f"{identity}.requiresはpluginとmarketplaceだけを宣言します")
        if any(not isinstance(dependency[key], str) or not dependency[key] for key in dependency):
            fail(f"{identity}.requiresに空または文字列以外の値があります")
        if dependency["plugin"] in external:
            fail(f"{identity}.requiresにpluginの重複があります")
        external.add(dependency["plugin"])
    steps = value["steps"]
    if not isinstance(steps, list) or not steps:
        fail(f"{identity}.stepsが非空配列ではありません")
    ids: set[str] = set()
    provided_at: dict[str, list[int]] = {}
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            fail(f"{identity}.steps[{index}]がmappingではありません")
        for provided in names(step.get("provides", []), f"{identity}.steps[{index}].provides", empty=True):
            provided_at.setdefault(provided, []).append(index)
    used_playbooks: set[str] = set()
    for index, step in enumerate(steps, 1):
        label = f"{identity}.steps[{index}]"
        actions = [key for key in ("agent_work", "script", "skill", "playbook") if key in step]
        if len(actions) != 1:
            fail(f"{label}はagent_work/script/skill/playbookのどれか1つだけを宣言します")
        if "agent_work" in step and step["agent_work"] != "invoking_agent":
            fail(f"{label}.agent_workがinvoking_agentではありません")
        if "agent_work" in step and (not isinstance(step.get("purpose"), str) or not step["purpose"]):
            fail(f"{label}.agent_workに非空purposeがありません")
        if not isinstance(step["id"], str) or not step["id"] or step["id"] in ids:
            fail(f"{label}.idが空または重複しています")
        ids.add(step["id"])
        needs = names(step.get("needs", []), f"{label}.needs", empty=True)
        for conditional in mappings(step.get("conditional_needs", []), f"{label}.conditional_needs"):
            if not isinstance(conditional.get("when"), str) or not conditional["when"]:
                fail(f"{label}.conditional_needs.whenが非空文字列ではありません")
            needs += names(conditional.get("needs", []), f"{label}.conditional_needs.needs", empty=True)
        missing = set(needs) - available
        if missing:
            origin = "後方工程" if any(item in provided_at for item in missing) else "公開入力または先行provides"
            fail(f"{label}.needsが{origin}で満たされません: {sorted(missing)}")
        provides = names(step.get("provides", []), f"{label}.provides", empty=True)
        duplicate = set(provides) & available
        if duplicate:
            fail(f"{label}.providesが既存値を上書きします: {sorted(duplicate)}")
        available.update(provides)
        if "script" in step:
            script = step["script"]
            if not isinstance(script, str) or not script or script.startswith("/"):
                fail(f"{label}.scriptが入口からの相対pathではありません")
            relative = Path(script)
            target = skill_root / relative
            if not relative.parts or relative.parts[0] != "scripts" or ".." in relative.parts or target.is_symlink() or not target.is_file():
                fail(f"{label}.scriptが入口のscripts/配下に実在しません: {script}")
        if "skill" in step:
            skill = step["skill"]
            if not isinstance(skill, str) or not skill or skill not in public_skills:
                fail(f"{label}.skillが公開宣言された実在skillではありません: {skill}")
        if "playbook" in step:
            playbook = step["playbook"]
            if not isinstance(playbook, str) or not playbook or playbook not in external:
                fail(f"{label}.playbookがrequiresに宣言されていません: {playbook}")
            used_playbooks.add(playbook)
    if external - used_playbooks:
        fail(f"{identity}.requiresに対応するplaybook工程がありません: {sorted(external - used_playbooks)}")


def identities(plugin: Path) -> list[str]:
    value = json.loads((plugin / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    return [Path(item).name for item in names(value.get("skills"), "manifest.skills")]


def validate(plugin: Path) -> None:
    declared = identities(plugin)
    for identity in declared:
        validate_playbook(plugin / "skills" / identity, identity, set(declared))


def replace(root: Path, identity: str, old: str, new: str) -> None:
    path = root / "skills" / identity / "playbook.yml"
    text = path.read_text(encoding="utf-8")
    if old not in text:
        fail(f"self-testの置換元がありません: {old}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_entry(root: Path, identity: str, old: str, new: str) -> None:
    path = root / "skills" / identity / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    if old not in text:
        fail(f"self-testの置換元がありません: {old}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_first_executor(root: Path, identity: str, action: str, target: str, prepare: bool = True, keep_purpose: bool = True) -> None:
    path = root / "skills" / identity / "playbook.yml"
    value = load_yaml(path)
    step = value["steps"][0]
    for key in ("agent_work", "script", "skill", "playbook"):
        step.pop(key, None)
    step[action] = target
    if not keep_purpose:
        step.pop("purpose", None)
    if action == "script" and prepare:
        script = root / "skills" / identity / target
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    elif action == "playbook" and prepare:
        value["requires"] = [{"plugin": target, "marketplace": "self-test"}]
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def self_test(plugin: Path) -> None:
    identity = identities(plugin)[0]
    equivalent_links = (
        ("ドット付き相対link", "[工程順序の正本](./playbook.yml)"),
        ("title付きlink", '[工程順序の正本](playbook.yml "工程順序")'),
        ("reference link", "[工程順序の正本][workflow]\n\n[workflow]: playbook.yml\n"),
        ("collapsed reference link", "[工程順序の正本][]\n\n[工程順序の正本]: playbook.yml\n"),
        ("shortcut reference link", "[工程順序の正本]\n\n[工程順序の正本]: playbook.yml\n"),
    )
    for label, replacement in equivalent_links:
        with tempfile.TemporaryDirectory(prefix="skill-playbook-contract-") as tmp:
            candidate = Path(tmp) / "plugin"
            shutil.copytree(plugin, candidate)
            replace_entry(candidate, identity, "[工程順序の正本](playbook.yml)", replacement)
            try:
                validate(candidate)
            except WorkflowError as exc:
                fail(f"正例「{label}」を拒否しました: {exc}")
    for action, target in (("script", "scripts/probe.sh"), ("skill", identity), ("playbook", "external-probe")):
        for keep_purpose in (True, False):
            with tempfile.TemporaryDirectory(prefix="skill-playbook-contract-") as tmp:
                candidate = Path(tmp) / "plugin"
                shutil.copytree(plugin, candidate)
                replace_first_executor(candidate, identity, action, target, keep_purpose=keep_purpose)
                try:
                    validate(candidate)
                except WorkflowError as exc:
                    qualifier = "purpose付き" if keep_purpose else "purpose無し"
                    fail(f"正例「{qualifier}{action}工程」を拒否しました: {exc}")
    mutations = (
        ("playbook欠落", lambda root: (root / "skills" / identity / "playbook.yml").unlink(), "regular file"),
        ("別fileへのlink", lambda root: replace_entry(root, identity, "[工程順序の正本](playbook.yml)", "[工程順序の正本](other.yml)"), "接続していません"),
        ("別file inlineと同名definition", lambda root: replace_entry(root, identity, "[工程順序の正本](playbook.yml)", "[工程順序の正本](other.yml)\n\n[工程順序の正本]: playbook.yml\n"), "接続していません"),
        ("未知need", lambda root: replace(root, identity, "agent_work: invoking_agent", "agent_work: invoking_agent\n    needs: [unknown]"), "公開入力または先行provides"),
        ("未知conditional need", lambda root: replace(root, identity, "agent_work: invoking_agent", "agent_work: invoking_agent\n    conditional_needs: [{when: branch, needs: [unknown]}]"), "公開入力または先行provides"),
        ("不存在script", lambda root: replace_first_executor(root, identity, "script", "scripts/missing.sh", False), "scripts/配下に実在しません"),
        ("未知skill", lambda root: replace_first_executor(root, identity, "skill", "missing-public-skill", False), "公開宣言された実在skill"),
        ("未宣言playbook", lambda root: replace_first_executor(root, identity, "playbook", "undeclared-playbook", False), "requiresに宣言されていません"),
        ("identity不一致", lambda root: replace(root, identity, f"name: {identity}", "name: wrong-identity"), "name"),
    )
    for label, mutate, expected in mutations:
        with tempfile.TemporaryDirectory(prefix="skill-playbook-contract-") as tmp:
            candidate = Path(tmp) / "plugin"
            shutil.copytree(plugin, candidate)
            mutate(candidate)
            try:
                validate(candidate)
            except WorkflowError as exc:
                if expected not in str(exc):
                    fail(f"負例「{label}」が別理由で失敗しました: {exc}")
            else:
                fail(f"負例「{label}」を拒否できません")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    plugin = args.plugin.resolve()
    validate(plugin)
    if args.self_test:
        self_test(plugin)
    print(f"Skill playbook contract: passed ({plugin})")


if __name__ == "__main__":
    try:
        main()
    except (WorkflowError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FAIL: {exc}")
