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
    ],
    "additionalProperties": False,
}

PASSING_REVIEW_JSON = (
    '{"complete": true, "reason": "dry run", "one_behavior_only": true, '
    '"minimal_green": true, "tests_unchanged_in_refactor": true, '
    '"acceptance_unit_boundary_ok": true, "forbidden_respected": true, "issues": []}'
)


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

    @classmethod
    def from_text(cls, text: str) -> ReviewGate:
        value = _parse_json_object(text)
        return cls(
            complete=bool(value.get("complete")),
            reason=str(value.get("reason") or ""),
            one_behavior_only=bool(value.get("one_behavior_only")),
            minimal_green=bool(value.get("minimal_green")),
            tests_unchanged_in_refactor=bool(value.get("tests_unchanged_in_refactor")),
            acceptance_unit_boundary_ok=bool(value.get("acceptance_unit_boundary_ok")),
            forbidden_respected=bool(value.get("forbidden_respected")),
            issues=[str(item) for item in value.get("issues", [])],
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
