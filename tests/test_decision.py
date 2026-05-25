from pathlib import Path

from aitdd.decision import CycleDecider
from aitdd.progress import ProgressStore
from aitdd.review import FollowUpReview, ReviewGate, UserQuestion
from aitdd.subjects import CycleSubject


def _review_gate(complete: bool = True) -> ReviewGate:
    return ReviewGate(
        complete=complete,
        reason="ok",
        one_behavior_only=True,
        minimal_green=True,
        tests_unchanged_in_refactor=True,
        acceptance_unit_boundary_ok=True,
        forbidden_respected=True,
    )


def test_cycle_decider_pauses_for_user_input(tmp_path: Path) -> None:
    progress = ProgressStore(tmp_path)
    follow_up = FollowUpReview(
        requirements_sufficient=False,
        needs_more_requirements=False,
        needs_more_tests=False,
        needs_user_input=True,
        questions_for_user=[
            UserQuestion(
                question="When should negative amounts fail?",
                reason="The invariant is unclear",
                blocks="negative amount behavior",
            )
        ],
    )

    decision = CycleDecider(progress).after_follow_up(
        _review_gate(),
        follow_up,
        CycleSubject("Money stores amount", "codex"),
    )

    assert decision.status == "needs_user_input"
    assert not decision.complete


def test_cycle_decider_completes_when_review_and_follow_up_are_clean(tmp_path: Path) -> None:
    progress = ProgressStore(tmp_path)
    follow_up = FollowUpReview(
        requirements_sufficient=True,
        needs_more_requirements=False,
        needs_more_tests=False,
        needs_user_input=False,
    )

    decision = CycleDecider(progress).after_follow_up(
        _review_gate(complete=True),
        follow_up,
        CycleSubject("cycle 1", "codex"),
    )

    assert decision.status == "completed"
    assert decision.complete
