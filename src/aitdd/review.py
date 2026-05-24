"""Structured Codex review gates."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

REVIEW_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "complete": {"type": "boolean"},
        "reason": {"type": "string"},
        "one_behavior_only": {"type": "boolean"},
        "minimal_green": {"type": "boolean"},
        "tests_unchanged_in_refactor": {"type": "boolean"},
        "acceptance_unit_boundary_ok": {"type": "boolean"},
        "forbidden_respected": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "needs_more_tests": {"type": "boolean"},
        "missing_test_perspectives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "behavior": {"type": "string"},
                    "reason": {"type": "string"},
                    "suggested_test": {"type": "string"},
                    "priority": {"type": "string"},
                },
                "required": ["behavior", "reason", "suggested_test", "priority"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "complete",
        "reason",
        "one_behavior_only",
        "minimal_green",
        "tests_unchanged_in_refactor",
        "acceptance_unit_boundary_ok",
        "forbidden_respected",
        "issues",
        "needs_more_tests",
        "missing_test_perspectives",
    ],
    "additionalProperties": False,
}

PASSING_REVIEW_JSON = (
    '{"complete": true, "reason": "dry run", "one_behavior_only": true, '
    '"minimal_green": true, "tests_unchanged_in_refactor": true, '
    '"acceptance_unit_boundary_ok": true, "forbidden_respected": true, '
    '"issues": [], "needs_more_tests": false, "missing_test_perspectives": []}'
)


@dataclass(frozen=True)
class MissingTestPerspective:
    behavior: str
    reason: str
    suggested_test: str
    priority: str = "medium"


@dataclass(frozen=True)
class ReviewGate:
    complete: bool
    reason: str
    one_behavior_only: bool
    minimal_green: bool
    tests_unchanged_in_refactor: bool
    acceptance_unit_boundary_ok: bool
    forbidden_respected: bool
    issues: list[str] = field(default_factory=list)
    needs_more_tests: bool = False
    missing_test_perspectives: list[MissingTestPerspective] = field(default_factory=list)

    @classmethod
    def from_text(cls, text: str) -> ReviewGate:
        value = _parse_json_object(text)
        missing = [
            _missing_test_perspective(item)
            for item in value.get("missing_test_perspectives", [])
        ]
        return cls(
            complete=bool(value.get("complete")),
            reason=str(value.get("reason") or ""),
            one_behavior_only=bool(value.get("one_behavior_only")),
            minimal_green=bool(value.get("minimal_green")),
            tests_unchanged_in_refactor=bool(value.get("tests_unchanged_in_refactor")),
            acceptance_unit_boundary_ok=bool(value.get("acceptance_unit_boundary_ok")),
            forbidden_respected=bool(value.get("forbidden_respected")),
            issues=[str(item) for item in value.get("issues", [])],
            needs_more_tests=bool(value.get("needs_more_tests")) or bool(missing),
            missing_test_perspectives=missing,
        )

    @property
    def passed(self) -> bool:
        return all(
            [
                self.one_behavior_only,
                self.minimal_green,
                self.tests_unchanged_in_refactor,
                self.acceptance_unit_boundary_ok,
                self.forbidden_respected,
            ]
        )

    def failure_message(self) -> str:
        failed = []
        if not self.one_behavior_only:
            failed.append("one_behavior_only=false")
        if not self.minimal_green:
            failed.append("minimal_green=false")
        if not self.tests_unchanged_in_refactor:
            failed.append("tests_unchanged_in_refactor=false")
        if not self.acceptance_unit_boundary_ok:
            failed.append("acceptance_unit_boundary_ok=false")
        if not self.forbidden_respected:
            failed.append("forbidden_respected=false")
        details = "; ".join(self.issues) if self.issues else self.reason
        return f"Codex review gate failed: {', '.join(failed)}. {details}"


def _parse_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Codex review did not return a JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Codex review JSON must be an object")
    return value


def _missing_test_perspective(value: Any) -> MissingTestPerspective:
    if not isinstance(value, dict):
        raise ValueError("missing_test_perspectives must contain objects")
    return MissingTestPerspective(
        behavior=str(value.get("behavior") or "").strip(),
        reason=str(value.get("reason") or "").strip(),
        suggested_test=str(value.get("suggested_test") or "").strip(),
        priority=str(value.get("priority") or "medium").strip() or "medium",
    )
