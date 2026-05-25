"""Cycle completion decisions."""

from __future__ import annotations

from dataclasses import dataclass

from .progress import ProgressStore
from .review import FollowUpReview, ReviewGate
from .spec import AitddSpec
from .subjects import CycleSubject


@dataclass(frozen=True)
class CycleDecision:
    status: str
    complete: bool


class CycleDecider:
    def __init__(
        self,
        progress: ProgressStore,
        spec: AitddSpec | None = None,
    ) -> None:
        self.progress = progress
        self.spec = spec

    def should_refactor(self, review_gate: ReviewGate, subject: CycleSubject) -> bool:
        return not self._complete_after_review(review_gate, subject)

    def after_follow_up(
        self,
        review_gate: ReviewGate,
        follow_up: FollowUpReview,
        subject: CycleSubject,
    ) -> CycleDecision:
        if follow_up.needs_user_input or self.progress.has_pending_user_questions():
            return CycleDecision("needs_user_input", complete=False)

        if (
            review_gate.needs_more_tests
            or self.progress.has_pending_test_backlog()
            or self.progress.has_pending_requirement_backlog()
            or follow_up.needs_more_work
        ):
            return CycleDecision("completed", complete=False)

        if self._spec_complete(subject):
            return CycleDecision("completed", complete=True)
        if self.spec and self.spec.cycles:
            return CycleDecision("completed", complete=False)
        return CycleDecision("completed", complete=review_gate.complete)

    def _complete_after_review(self, review_gate: ReviewGate, subject: CycleSubject) -> bool:
        if review_gate.needs_more_tests or self.progress.has_pending_test_backlog():
            return False
        if self.progress.has_pending_requirement_backlog():
            return False
        if self.progress.has_pending_user_questions():
            return False
        if self.spec and self.spec.cycles:
            return self._spec_complete(subject)
        return review_gate.complete

    def _spec_complete(self, subject: CycleSubject) -> bool:
        if not self.spec or not self.spec.cycles:
            return False
        completed_spec_cycles = self.progress.completed_spec_cycle_count()
        if subject.source == "spec":
            completed_spec_cycles += 1
        return completed_spec_cycles >= len(self.spec.cycles)
