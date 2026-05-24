"""Draft aitdd.yaml specs with Codex."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .agents import Agent, CodexSdkAgent, DryRunAgent

PLAN_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "public_api": {"type": "array", "items": {"type": "string"}},
        "forbidden": {"type": "array", "items": {"type": "string"}},
        "acceptance_tests": {"type": "array", "items": {"type": "string"}},
        "unit_tests": {"type": "array", "items": {"type": "string"}},
        "done_when": {"type": "array", "items": {"type": "string"}},
        "acceptance_test_command": {"type": ["string", "null"]},
        "cycles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "behavior": {"type": "string"},
                    "notes": {"type": "array", "items": {"type": "string"}},
                    "expected_red": {
                        "type": ["object", "null"],
                        "properties": {
                            "exit_code": {"type": "string"},
                            "must_include": {"type": "array", "items": {"type": "string"}},
                            "must_not_include": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["exit_code", "must_include", "must_not_include"],
                        "additionalProperties": False,
                    },
                },
                "required": ["behavior", "notes", "expected_red"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "goal",
        "constraints",
        "public_api",
        "forbidden",
        "acceptance_tests",
        "unit_tests",
        "done_when",
        "acceptance_test_command",
        "cycles",
    ],
    "additionalProperties": False,
}


def draft_spec_yaml(
    goal: str,
    workdir: Path,
    codex_model: str | None = None,
    dry_run: bool = False,
    planner: Agent | None = None,
) -> str:
    agent = planner or (
        DryRunAgent("codex-planner") if dry_run else CodexSdkAgent(model=codex_model)
    )
    if dry_run and isinstance(agent, DryRunAgent):
        return render_spec_yaml(_dry_run_spec(goal))

    prompt = f"""
あなたは aitdd.yaml を作る Codex 計画担当です。
作業ディレクトリを読み、t-wada 流 TDD で実装しやすい最小 spec draft を作ってください。
実装やファイル編集は絶対にしないでください。

方針:
- 1 cycle は 1 つの public behavior だけにしてください
- acceptance_tests と unit_tests を分けてください
- forbidden には先回り実装、テスト無し実装、複数 behavior 同時追加を含めてください
- done_when には all_cycles_complete, acceptance_tests_pass,
  no_review_gate_failures を含めてください
- cycles は最初から完璧にしすぎず、最小で始められる粒度にしてください

ゴール:
{goal}

JSON schema に従った JSON だけを返してください。
""".strip()
    result = agent.run(prompt, workdir, PLAN_SCHEMA)
    if not result.ok:
        raise RuntimeError(
            f"{result.role} failed with exit code {result.returncode}\n{result.stderr}"
        )
    return render_spec_yaml(_parse_json_object(result.stdout))


def render_spec_yaml(value: dict[str, Any]) -> str:
    return yaml.safe_dump(_clean_spec(value), allow_unicode=True, sort_keys=False)


def _dry_run_spec(goal: str) -> dict[str, Any]:
    return {
        "goal": goal,
        "constraints": [
            "1 cycle で追加してよい public behavior は 1 つだけ",
            "RED は期待した理由で失敗させる",
            "GREEN は失敗を通す最小実装に限る",
            "REFACTOR ではテストを変更しない",
        ],
        "public_api": [],
        "forbidden": [
            "テスト無しの先回り実装",
            "複数 behavior の同時追加",
            "REFACTOR フェーズでのテスト変更",
        ],
        "acceptance_tests": [],
        "unit_tests": [],
        "done_when": [
            "all_cycles_complete",
            "acceptance_tests_pass",
            "no_review_gate_failures",
        ],
        "acceptance_test_command": None,
        "cycles": [
            {
                "behavior": f"first observable behavior for {goal}",
                "notes": ["最初の RED として観測可能な最小テストを 1 つだけ追加する"],
                "expected_red": None,
            }
        ],
    }


def _clean_spec(value: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {
        "goal": str(value.get("goal") or "").strip(),
        "constraints": _string_list(value.get("constraints")),
        "public_api": _string_list(value.get("public_api")),
        "forbidden": _string_list(value.get("forbidden")),
        "acceptance_tests": _string_list(value.get("acceptance_tests")),
        "unit_tests": _string_list(value.get("unit_tests")),
        "done_when": _string_list(value.get("done_when"))
        or ["all_cycles_complete", "acceptance_tests_pass", "no_review_gate_failures"],
        "cycles": [],
    }
    command = value.get("acceptance_test_command")
    if command:
        cleaned["acceptance_test_command"] = str(command)

    for item in value.get("cycles", []):
        if not isinstance(item, dict):
            continue
        cycle: dict[str, Any] = {"behavior": str(item.get("behavior") or "").strip()}
        notes = _string_list(item.get("notes"))
        if notes:
            cycle["notes"] = notes
        expected_red = item.get("expected_red")
        if isinstance(expected_red, dict):
            cycle["expected_red"] = {
                "exit_code": str(expected_red.get("exit_code") or "nonzero"),
                "must_include": _string_list(expected_red.get("must_include")),
                "must_not_include": _string_list(expected_red.get("must_not_include")),
            }
        if cycle["behavior"]:
            cleaned["cycles"].append(cycle)
    if not cleaned["cycles"]:
        cleaned["cycles"] = _dry_run_spec(cleaned["goal"])["cycles"]
    return cleaned


def _parse_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Codex plan did not return a JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Codex plan JSON must be an object")
    return value


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value if str(item).strip()]
