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
from .review import (
    FOLLOW_UP_SCHEMA,
    PASSING_FOLLOW_UP_JSON,
    PASSING_REVIEW_JSON,
    REVIEW_SCHEMA,
    FollowUpReview,
    ReviewGate,
)
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
    follow_up: FollowUpReview


@dataclass(frozen=True)
class CycleSubject:
    behavior: str
    source: str
    cycle: CycleSpec | None = None
    backlog_item: dict[str, object] | None = None
    requirement_item: dict[str, object] | None = None


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
                subject = self._cycle_subject(index)
                plan = self._plan(index, subject)
                current_progress = self.progress.start_cycle(
                    index,
                    subject.behavior,
                    plan,
                    source=subject.source,
                    backlog_item_id=_backlog_item_id(
                        subject.backlog_item or subject.requirement_item
                    ),
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

                complete = self._is_complete(review_gate, None, subject)
                if not complete:
                    tests_before = self._snapshot_test_files()
                    self._implement(TddPhase.REFACTOR, review)
                    self._require_refactor_kept_tests(tests_before)
                refactor = self._run_tests(TddPhase.REFACTOR)
                self.progress.record_phase(current_progress, "refactor", refactor)
                self._require(TddPhase.REFACTOR, refactor)

                follow_up_text = self._follow_up(index, plan, review, refactor)
                follow_up = FollowUpReview.from_text(follow_up_text)
                self.progress.record_follow_up(current_progress, follow_up)
                complete = self._is_complete(review_gate, follow_up, subject)

                if complete:
                    self._require_done_when()

                status = "completed" if complete else "completed"
                self.progress.finish_cycle(current_progress, status)
                results.append(
                    CycleResult(
                        index,
                        red,
                        green,
                        refactor,
                        complete,
                        review,
                        review_gate,
                        follow_up,
                    )
                )
                if complete:
                    break
        except Exception as exc:
            self.progress.fail_cycle(current_progress, exc)
            raise
        return results

    def _cycle_subject(self, index: int) -> CycleSubject:
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

    def _plan(self, index: int, subject: CycleSubject) -> str:
        spec_text = self.spec.describe() if self.spec else f"Goal:\n{self.config.goal}"
        cycle_text = self._subject_text(index, subject)
        prompt = f"""
あなたは t-wada さんの TDD の進め方を尊重する計画担当です。
作業ディレクトリを読み、次の最小の RED を 1 つだけ計画してください。
実装やファイル編集は絶対にしないでください。
1 サイクルで追加してよい public behavior は 1 つだけです。
acceptance test と unit test の境界を守ってください。
Codex レビューで不足テスト観点が見つかった場合は、それを次の RED として扱います。

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

    def _subject_text(self, index: int, subject: CycleSubject) -> str:
        if subject.requirement_item:
            return self._requirement_text(subject.requirement_item)
        if subject.backlog_item:
            return self._backlog_text(subject.backlog_item)
        if subject.cycle:
            return self._cycle_text(subject.cycle)
        backlog = self.progress.pending_test_perspectives()
        if backlog:
            lines = [
                "Codex レビューが見つけた不足テスト観点があります。",
                "次の RED は pending backlog から 1 つだけ選んでください。",
            ]
            lines.extend(
                f"- {item.get('priority', 'medium')} {item.get('behavior')}: "
                f"{item.get('suggested_test')}"
                for item in backlog
            )
            return "\n".join(lines)
        return f"Cycle {index}: Codex が次の最小 public behavior を 1 つだけ選んでください。"

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

    def _backlog_text(self, item: dict[str, object]) -> str:
        return "\n".join(
            [
                "Codex レビューが追加した不足テスト観点です。",
                f"Behavior: {item.get('behavior')}",
                f"Reason: {item.get('reason')}",
                f"Suggested test: {item.get('suggested_test')}",
                f"Priority: {item.get('priority', 'medium')}",
            ]
        )

    def _requirement_text(self, item: dict[str, object]) -> str:
        return "\n".join(
            [
                "Follow Up が追加した不足要件です。",
                f"Requirement: {item.get('requirement')}",
                f"Reason: {item.get('reason')}",
                f"Suggested behavior: {item.get('suggested_behavior')}",
                f"Priority: {item.get('priority', 'medium')}",
            ]
        )

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
- 仕様、実装、既存テストから見て足りないテスト観点がないか

足りないテスト観点がある場合:
- gate 自体が通るなら issues ではなく missing_test_perspectives に入れてください
- needs_more_tests を true にしてください
- missing_test_perspectives は次 cycle の RED 候補になります
- 1 要素は 1 つの public behavior または 1 つの境界条件だけにしてください

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

    def _follow_up(
        self,
        index: int,
        plan: str,
        review: str,
        test_run: PhaseTestResult,
    ) -> str:
        if self.config.dry_run and isinstance(self.planner, DryRunAgent):
            return PASSING_FOLLOW_UP_JSON

        goal = self.spec.describe() if self.spec else self.config.goal
        prompt = f"""
あなたは Codex Follow Up 担当です。
今回の RED-GREEN-REFACTOR 後に、要件やテスト観点の抜け漏れを振り返ってください。
実装やファイル編集は絶対にしないでください。

確認すること:
- ゴールや spec に対して、まだ明文化されていない要件がないか
- 今回の実装に対して、追加で RED にすべき境界値、例外系、責務分離のテストがないか
- 見つけたものは 1 項目 1 behavior または 1 テスト観点に分ける
- 既に covered なものは重複して返さない

ゴール:
{goal}

サイクル: {index}
計画:
{plan}

Codex review:
{review}

テスト結果:
command: {test_run.command}
returncode: {test_run.returncode}

最後は必ず JSON schema に従った JSON だけを返してください。
""".strip()
        if isinstance(self.planner, CodexSdkAgent):
            return self.planner.run(prompt, self.config.workdir, FOLLOW_UP_SCHEMA).stdout
        return self._run_agent(self.planner, prompt).stdout

    def _is_complete(
        self,
        review_gate: ReviewGate,
        follow_up: FollowUpReview | None,
        subject: CycleSubject,
    ) -> bool:
        if review_gate.needs_more_tests or self.progress.has_pending_test_backlog():
            return False
        if self.progress.has_pending_requirement_backlog():
            return False
        if follow_up and follow_up.needs_more_work:
            return False
        if self.spec and self.spec.cycles:
            completed_spec_cycles = self.progress.completed_spec_cycle_count()
            if subject.source == "spec":
                completed_spec_cycles += 1
            return completed_spec_cycles >= len(self.spec.cycles)
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


def _backlog_item_id(item: dict[str, object] | None) -> str | None:
    if not item:
        return None
    value = item.get("id")
    return str(value) if value is not None else None
