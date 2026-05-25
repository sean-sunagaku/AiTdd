from aitdd.application.prompts import PromptBuilder
from aitdd.application.subjects import CycleSubject
from aitdd.domain.policy import PhaseTestResult, TddPhase


def test_prompt_builder_renders_follow_up_clarification_gate_instruction() -> None:
    prompt = PromptBuilder(goal="Build Money").follow_up(
        index=1,
        plan="plan",
        review="review",
        test_run=PhaseTestResult("pytest", 0),
    )

    assert "needs_user_input" in prompt
    assert "questions_for_user" in prompt
    assert "AI が推定して進めるべきではない仕様判断" in prompt


def test_prompt_builder_renders_implement_phase_instruction() -> None:
    prompt = PromptBuilder(goal="Build Money").implement(TddPhase.RED, "plan")

    assert "現在フェーズ: RED" in prompt
    assert "失敗する最小テストだけ" in prompt


def test_prompt_builder_renders_codex_cycle_subject() -> None:
    prompt = PromptBuilder(goal="Build Money").plan(1, CycleSubject("cycle 1", "codex"))

    assert "Goal:" in prompt
    assert "次の最小 public behavior" in prompt
