"""RED-GREEN-REFACTOR orchestration."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .agents import (
    Agent,
    AgentResult,
    CodexSdkAgent,
    CursorCliAgent,
    CursorSdkAgent,
    DryRunAgent,
)
from .hook_policy import PhaseTestResult, TddPhase, evaluate_phase
from .progress import CycleProgress, ProgressStore
from .review import PASSING_REVIEW_JSON, REVIEW_SCHEMA, ReviewGate
from .spec import AitddSpec, CycleSpec


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
                cycle = self._cycle_for(index)
                plan = self._plan(index, cycle)
                current_progress = self.progress.start_cycle(
                    index,
                    self._behavior(index, cycle),
                    plan,
                )

                self._implement(TddPhase.RED, plan)
                red = self._run_tests(TddPhase.RED, cycle)
                self.progress.record_phase(current_progress, "red", red)
                self._require(TddPhase.RED, red, cycle)

                self._implement(TddPhase.GREEN, plan)
                green = self._run_tests(TddPhase.GREEN)
                self.progress.record_phase(current_progress, "green", green)
                self._require(TddPhase.GREEN, green)

                review = self._review(index, plan, green)
                review_gate = ReviewGate.from_text(review)
                self.progress.record_review(current_progress, review_gate)
                self._require_review_gate(review_gate)

                complete = self._is_complete(review_gate, index)
                if not complete:
                    tests_before = self._snapshot_test_files()
                    self._implement(TddPhase.REFACTOR, review)
                    self._require_refactor_kept_tests(tests_before)
                refactor = self._run_tests(TddPhase.REFACTOR)
                self.progress.record_phase(current_progress, "refactor", refactor)
                self._require(TddPhase.REFACTOR, refactor)

                if complete:
                    self._require_done_when()

                status = "completed" if complete else "completed"
                self.progress.finish_cycle(current_progress, status)
                results.append(
                    CycleResult(index, red, green, refactor, complete, review, review_gate)
                )
                if complete:
                    break
        except Exception as exc:
            self.progress.fail_cycle(current_progress, exc)
            raise
        return results

    def _cycle_for(self, index: int) -> CycleSpec | None:
        if not self.spec or index > len(self.spec.cycles):
            return None
        return self.spec.cycles[index - 1]

    def _behavior(self, index: int, cycle: CycleSpec | None) -> str:
        return cycle.behavior if cycle else f"cycle {index}"

    def _plan(self, index: int, cycle: CycleSpec | None) -> str:
        spec_text = self.spec.describe() if self.spec else f"Goal:\n{self.config.goal}"
        cycle_text = (
            self._cycle_text(cycle)
            if cycle
            else "Codex が次の最小 public behavior を 1 つだけ選んでください。"
        )
        prompt = f"""
あなたは t-wada さんの TDD の進め方を尊重する計画担当です。
作業ディレクトリを読み、次の最小の RED を 1 つだけ計画してください。
実装やファイル編集は絶対にしないでください。
1 サイクルで追加してよい public behavior は 1 つだけです。
acceptance test と unit test の境界を守ってください。

仕様:
{spec_text}

サイクル: {index}
今回の対象:
{cycle_text}

出力は次を含めてください:
- 次に追加する最小テスト
- 期待する失敗理由
- GREEN で許される最小実装
- リファクタリング観点
""".strip()
        return self._run_agent(self.planner, prompt).stdout

    def _cycle_text(self, cycle: CycleSpec) -> str:
        lines = [f"Behavior: {cycle.behavior}"]
        if cycle.expected_red_failure:
            lines.append("Expected RED failure:")
            lines.append(f"- exit_code: {cycle.expected_red_failure.exit_code}")
            for item in cycle.expected_red_failure.must_include or []:
                lines.append(f"- must_include: {item}")
            for item in cycle.expected_red_failure.must_not_include or []:
                lines.append(f"- must_not_include: {item}")
        if cycle.notes:
            lines.append("Notes:")
            lines.extend(f"- {item}" for item in cycle.notes)
        return "\n".join(lines)

    def _implement(self, phase: TddPhase, context: str) -> None:
        prompts = {
            TddPhase.RED: (
                "失敗する最小テストだけを書いてください。"
                "プロダクトコードは原則変更しないでください。"
            ),
            TddPhase.GREEN: "今ある失敗を通すための最小実装だけを書いてください。",
            TddPhase.REFACTOR: (
                "テストを通したまま設計を少しだけ良くしてください。"
                "振る舞いは変えないでください。テストファイルは変更しないでください。"
            ),
        }
        prompt = f"""
あなたは Cursor 実装担当です。t-wada 流の RED-GREEN-REFACTOR を厳守します。
現在フェーズ: {phase.value.upper()}

指示:
{prompts[phase]}
- 1 サイクルで追加してよい public behavior は 1 つだけです。
- まだテストされていない先回り実装は禁止です。
- 受け入れテストとユニットテストの責務を混ぜないでください。

計画またはレビュー:
{context}
""".strip()
        self._run_agent(self.implementer, prompt)

    def _review(self, index: int, plan: str, test_run: PhaseTestResult) -> str:
        if self.config.dry_run and isinstance(self.planner, DryRunAgent):
            return PASSING_REVIEW_JSON

        goal = self.spec.describe() if self.spec else self.config.goal
        prompt = f"""
あなたは Codex レビュー担当です。作業ディレクトリを読み、TDD サイクルの品質をレビューしてください。
実装やファイル編集は絶対にしないでください。
次を厳しく確認してください:
- 1 サイクルで public behavior が 1 つだけ増えているか
- GREEN は RED を通す最小差分か
- REFACTOR でテストが変更されていないか
- 受け入れテストとユニットテストの境界が守られているか
- forbidden に触れていないか

ゴール:
{goal}

サイクル: {index}
計画:
{plan}

テスト結果:
command: {test_run.command}
returncode: {test_run.returncode}

最後は必ず JSON schema に従った JSON だけを返してください。
""".strip()
        if isinstance(self.planner, CodexSdkAgent):
            return self.planner.run(prompt, self.config.workdir, REVIEW_SCHEMA).stdout
        return self._run_agent(self.planner, prompt).stdout

    def _is_complete(self, review_gate: ReviewGate, index: int) -> bool:
        if self.spec and self.spec.cycles:
            return index >= len(self.spec.cycles)
        return review_gate.complete

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

        completed = subprocess.run(
            self.config.test_command,
            cwd=self.config.workdir,
            shell=True,
            text=True,
            capture_output=True,
            check=False,
        )
        return PhaseTestResult(
            command=self.config.test_command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _run_command(self, command: str) -> PhaseTestResult:
        completed = subprocess.run(
            command,
            cwd=self.config.workdir,
            shell=True,
            text=True,
            capture_output=True,
            check=False,
        )
        return PhaseTestResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

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

    def _snapshot_test_files(self) -> dict[Path, str]:
        snapshots: dict[Path, str] = {}
        for path in self.config.workdir.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.name.startswith("test_") or path.parent.name in {"tests", "test"}:
                snapshots[path.relative_to(self.config.workdir)] = path.read_text(errors="ignore")
        return snapshots

    def _require_refactor_kept_tests(self, before: dict[Path, str]) -> None:
        after = self._snapshot_test_files()
        if before != after:
            raise RuntimeError("REFACTOR rejected: test files changed during refactor phase.")

    def _run_agent(self, agent: Agent, prompt: str) -> AgentResult:
        result = agent.run(prompt, self.config.workdir)
        if not result.ok:
            raise RuntimeError(
                f"{result.role} failed with exit code {result.returncode}\n{result.stderr}"
            )
        return result
