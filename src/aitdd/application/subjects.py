"""Cycle subject selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aitdd.domain.spec import AitddSpec, CycleSpec
from aitdd.infrastructure.progress import ProgressStore


@dataclass(frozen=True)
class CycleSubject:
    behavior: str
    source: str
    cycle: CycleSpec | None = None
    backlog_item: dict[str, Any] | None = None
    requirement_item: dict[str, Any] | None = None

    @property
    def backlog_item_id(self) -> str | None:
        item = self.backlog_item or self.requirement_item
        if not item:
            return None
        value = item.get("id")
        return str(value) if value is not None else None


class CycleSubjectSelector:
    def __init__(self, progress: ProgressStore, spec: AitddSpec | None = None) -> None:
        self.progress = progress
        self.spec = spec

    def select(self, index: int) -> CycleSubject:
        if self.progress.has_pending_user_questions():
            raise RuntimeError(
                "Clarification Gate is waiting for user input. "
                "Resolve .aitdd/progress.json questions_for_user before resuming."
            )

        requirement_item = self.progress.claim_next_requirement(index)
        if requirement_item:
            return CycleSubject(
                behavior=str(
                    requirement_item.get("suggested_behavior")
                    or requirement_item.get("requirement")
                    or f"missing requirement {index}"
                ),
                source="requirements_backlog",
                requirement_item=requirement_item,
            )

        backlog_item = self.progress.claim_next_test_perspective(index)
        if backlog_item:
            return CycleSubject(
                behavior=str(backlog_item.get("behavior") or f"missing test {index}"),
                source="test_backlog",
                backlog_item=backlog_item,
            )

        if self.spec and self.spec.cycles:
            spec_index = self.progress.completed_spec_cycle_count()
            if spec_index < len(self.spec.cycles):
                cycle = self.spec.cycles[spec_index]
                return CycleSubject(
                    behavior=cycle.behavior,
                    source="spec",
                    cycle=cycle,
                )

        return CycleSubject(behavior=f"cycle {index}", source="codex")
