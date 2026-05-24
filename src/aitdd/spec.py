"""Specification support for complex TDD loops."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .hook_policy import ExpectedRed


@dataclass(frozen=True)
class CycleSpec:
    behavior: str
    expected_red_failure: ExpectedRed | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AitddSpec:
    goal: str
    constraints: list[str] = field(default_factory=list)
    public_api: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    acceptance_tests: list[str] = field(default_factory=list)
    unit_tests: list[str] = field(default_factory=list)
    done_when: list[str] = field(default_factory=lambda: ["all_cycles_complete"])
    acceptance_test_command: str | None = None
    cycles: list[CycleSpec] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> AitddSpec:
        raw = yaml.safe_load(path.read_text()) or {}
        if not isinstance(raw, dict):
            raise ValueError("aitdd spec must be a YAML mapping")

        goal = str(raw.get("goal") or "").strip()
        if not goal:
            raise ValueError("aitdd spec requires a non-empty 'goal'")

        return cls(
            goal=goal,
            constraints=[str(item) for item in _list(raw.get("constraints"))],
            public_api=[str(item) for item in _list(raw.get("public_api"))],
            forbidden=[str(item) for item in _list(raw.get("forbidden"))],
            acceptance_tests=[str(item) for item in _list(raw.get("acceptance_tests"))],
            unit_tests=[str(item) for item in _list(raw.get("unit_tests"))],
            done_when=[str(item) for item in _list(raw.get("done_when"))]
            or ["all_cycles_complete"],
            acceptance_test_command=(
                str(raw["acceptance_test_command"])
                if raw.get("acceptance_test_command") is not None
                else None
            ),
            cycles=[_cycle_from_raw(item) for item in _list(raw.get("cycles"))],
        )

    def describe(self) -> str:
        sections = [f"Goal:\n{self.goal}"]
        sections.append(_format_list("Constraints", self.constraints))
        sections.append(_format_list("Public API", self.public_api))
        sections.append(_format_list("Forbidden", self.forbidden))
        sections.append(_format_list("Acceptance tests", self.acceptance_tests))
        sections.append(_format_list("Unit tests", self.unit_tests))
        return "\n\n".join(section for section in sections if section)


def _cycle_from_raw(raw: Any) -> CycleSpec:
    if isinstance(raw, str):
        return CycleSpec(behavior=raw)
    if not isinstance(raw, dict):
        raise ValueError("each cycle must be a string or mapping")

    behavior = str(raw.get("behavior") or "").strip()
    if not behavior:
        raise ValueError("cycle mapping requires 'behavior'")

    return CycleSpec(
        behavior=behavior,
        expected_red_failure=_expected_red_from_raw(raw),
        notes=[str(item) for item in _list(raw.get("notes"))],
    )


def _expected_red_from_raw(raw: dict[str, Any]) -> ExpectedRed | None:
    if "expected_red" in raw:
        value = raw["expected_red"]
        if not isinstance(value, dict):
            raise ValueError("expected_red must be a mapping")
        return ExpectedRed(
            exit_code=str(value.get("exit_code") or "nonzero"),
            must_include=[str(item) for item in _list(value.get("must_include"))],
            must_not_include=[str(item) for item in _list(value.get("must_not_include"))],
        )

    legacy = [str(item) for item in _list(raw.get("expected_red_failure"))]
    if not legacy:
        return None
    return ExpectedRed(must_include=legacy)


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _format_list(title: str, items: list[str]) -> str:
    if not items:
        return ""
    body = "\n".join(f"- {item}" for item in items)
    return f"{title}:\n{body}"
