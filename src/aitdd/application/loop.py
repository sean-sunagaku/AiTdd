"""RED-GREEN-REFACTOR orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aitdd.domain.policy import PhaseTestResult, TddPhase, evaluate_phase
from aitdd.domain.review import (
    FOLLOW_UP_SCHEMA,
    PASSING_FOLLOW_UP_JSON,
    PASSING_REVIEW_JSON,
    REVIEW_SCHEMA,
    FollowUpReview,
    ReviewGate,
)
from aitdd.domain.spec import AitddSpec, CycleSpec
from aitdd.infrastructure.agents import (
    Agent,
    AgentResult,
    CodexSdkAgent,
    CursorCliAgent,
    CursorSdkAgent,
    DryRunAgent,
)
from aitdd.infrastructure.progress import CycleProgress, ProgressStore
from aitdd.infrastructure.testing import WorkspaceTester

from .decision import CycleDecider
from .prompts import PromptBuilder
from .subjects import CycleSubject, CycleSubjectSelector


@dataclass(frozen=True)
class TddLoopConfig:
    goal: str
    workdir: Path
    test_command: str = "pytest"
    max_cycles: int = 5
    codex_model: str | None = None
    cursor_model: str | None = None
    cursor_backend: str = "sdk"
    spec_path: Path | None = None
    resume: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class CycleResult:
    index: int
    red: PhaseTestResult
    green: PhaseTestResult
    refactor: PhaseTestResult
    complete: bool
    review: str
    review_gate: ReviewGate
    follow_up: FollowUpReview


class TddLoop:
    def __init__(
        self,
        config: TddLoopConfig,
        planner: Agent | None = None,
        implementer: Agent | None = None,
    ) -> None:
        self.config = config
        self.spec = AitddSpec.from_file(config.spec_path) if config.spec_path else None
        self.progress = ProgressStore(config.workdir)
        self.subjects = CycleSubjectSelector(self.progress, self.spec)
        self.decider = CycleDecider(self.progress, self.spec)
        self.prompts = PromptBuilder(config.goal, self.spec)
        self.tester = WorkspaceTester(config.workdir, config.test_command)
        self.planner = planner or (
            DryRunAgent("codex-planner")
            if config.dry_run
            else CodexSdkAgent(model=config.codex_model)
        )
        self.implementer = implementer or (
            DryRunAgent("cursor-implementer")
            if config.dry_run
            else self._create_cursor_agent()
        )

    def _create_cursor_agent(self) -> Agent:
        model = self.config.cursor_model or "composer-latest"
        if self.config.cursor_backend == "cli":
            return CursorCliAgent(model=model)
        if self.config.cursor_backend == "sdk":
            return CursorSdkAgent(model=model)
        raise ValueError(f"Unsupported cursor backend: {self.config.cursor_backend}")

    def run(self) -> list[CycleResult]:
        results: list[CycleResult] = []
        start_index = self.progress.next_cycle_index() if self.config.resume else 1
        current_progress: CycleProgress | None = None
        try:
            for index in range(start_index, self.config.max_cycles + 1):
                subject = self.subjects.select(index)
                plan = self._plan(index, subject)
                current_progress = self.progress.start_cycle(
                    index,
                    subject.behavior,
                    plan,
                    source=subject.source,
                    backlog_item_id=subject.backlog_item_id,
                )

                self._implement(TddPhase.RED, plan)
                red = self._run_tests(TddPhase.RED, subject.cycle)
                self.progress.record_phase(current_progress, "red", red)
                self._require(TddPhase.RED, red, subject.cycle)

                self._implement(TddPhase.GREEN, plan)
                green = self._run_tests(TddPhase.GREEN)
                self.progress.record_phase(current_progress, "green", green)
                self._require(TddPhase.GREEN, green)

                review = self._review(index, plan, green)
                review_gate = ReviewGate.from_text(review)
                self.progress.record_review(current_progress, review_gate)
                self._require_review_gate(review_gate)

                if self.decider.should_refactor(review_gate, subject):
                    tests_before = self.tester.snapshot_test_files()
                    self._implement(TddPhase.REFACTOR, review)
                    self.tester.require_refactor_kept_tests(tests_before)
                refactor = self._run_tests(TddPhase.REFACTOR)
                self.progress.record_phase(current_progress, "refactor", refactor)
                self._require(TddPhase.REFACTOR, refactor)

                follow_up_text = self._follow_up(index, plan, review, refactor)
                follow_up = FollowUpReview.from_text(follow_up_text)
                self.progress.record_follow_up(current_progress, follow_up)
                decision = self.decider.after_follow_up(review_gate, follow_up, subject)
                if decision.status == "needs_user_input":
                    self.progress.finish_cycle(current_progress, decision.status)
                    results.append(
                        CycleResult(
                            index,
                            red,
                            green,
                            refactor,
                            False,
                            review,
                            review_gate,
                            follow_up,
                        )
                    )
                    break

                if decision.complete:
                    self._require_done_when()

                self.progress.finish_cycle(current_progress, decision.status)
                results.append(
                    CycleResult(
                        index,
                        red,
                        green,
                        refactor,
                        decision.complete,
                        review,
                        review_gate,
                        follow_up,
                    )
                )
                if decision.complete:
                    break
        except Exception as exc:
            self.progress.fail_cycle(current_progress, exc)
            raise
        return results

    def _plan(self, index: int, subject: CycleSubject) -> str:
        return self._run_agent(self.planner, self.prompts.plan(index, subject)).stdout

    def _implement(self, phase: TddPhase, context: str) -> None:
        self._run_agent(self.implementer, self.prompts.implement(phase, context))

    def _review(self, index: int, plan: str, test_run: PhaseTestResult) -> str:
        if self.config.dry_run and isinstance(self.planner, DryRunAgent):
            return PASSING_REVIEW_JSON

        prompt = self.prompts.review(index, plan, test_run)
        if isinstance(self.planner, CodexSdkAgent):
            return self.planner.run(prompt, self.config.workdir, REVIEW_SCHEMA).stdout
        return self._run_agent(self.planner, prompt).stdout

    def _follow_up(
        self,
        index: int,
        plan: str,
        review: str,
        test_run: PhaseTestResult,
    ) -> str:
        if self.config.dry_run and isinstance(self.planner, DryRunAgent):
            return PASSING_FOLLOW_UP_JSON

        prompt = self.prompts.follow_up(index, plan, review, test_run)
        if isinstance(self.planner, CodexSdkAgent):
            return self.planner.run(prompt, self.config.workdir, FOLLOW_UP_SCHEMA).stdout
        return self._run_agent(self.planner, prompt).stdout

    def _require_done_when(self) -> None:
        if not self.spec or "acceptance_tests_pass" not in self.spec.done_when:
            return

        command = self.spec.acceptance_test_command
        if not command and self.spec.acceptance_tests:
            command = "pytest " + " ".join(self.spec.acceptance_tests)
        command = command or self.config.test_command
        result = self._run_command(command)
        if result.failed:
            raise RuntimeError("done_when rejected: acceptance_tests_pass failed.")

    def _require_review_gate(self, review_gate: ReviewGate) -> None:
        if not review_gate.passed:
            raise RuntimeError(review_gate.failure_message())

    def _run_tests(
        self,
        phase: TddPhase,
        cycle: CycleSpec | None = None,
    ) -> PhaseTestResult:
        if self.config.dry_run:
            code = 1 if phase is TddPhase.RED else 0
            stderr = ""
            if phase is TddPhase.RED and cycle and cycle.expected_red_failure:
                includes = cycle.expected_red_failure.must_include or []
                stderr = f"{includes[0]} [dry-run]\n" if includes else "expected RED [dry-run]\n"
            return PhaseTestResult(
                self.config.test_command,
                code,
                stdout=f"[dry-run:{phase.value}]\n",
                stderr=stderr,
            )

        return self.tester.run_tests()

    def _run_command(self, command: str) -> PhaseTestResult:
        return self.tester.run_command(command)

    def _require(
        self,
        phase: TddPhase,
        test_run: PhaseTestResult,
        cycle: CycleSpec | None = None,
    ) -> None:
        expected = cycle.expected_red_failure if cycle else None
        decision = evaluate_phase(phase, test_run, expected)
        if decision.denied:
            raise RuntimeError(decision.reason)

    def _run_agent(self, agent: Agent, prompt: str) -> AgentResult:
        result = agent.run(prompt, self.config.workdir)
        if not result.ok:
            raise RuntimeError(
                f"{result.role} failed with exit code {result.returncode}\n{result.stderr}"
            )
        return result
