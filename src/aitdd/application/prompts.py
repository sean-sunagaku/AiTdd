"""Prompt construction for Codex and Cursor roles."""

from __future__ import annotations

from aitdd.domain.policy import PhaseTestResult, TddPhase
from aitdd.domain.spec import AitddSpec, CycleSpec

from .subjects import CycleSubject


class PromptBuilder:
    def __init__(self, goal: str, spec: AitddSpec | None = None) -> None:
        self.goal = goal
        self.spec = spec

    def plan(self, index: int, subject: CycleSubject) -> str:
        spec_text = self.spec.describe() if self.spec else f"Goal:\n{self.goal}"
        cycle_text = self.subject_text(index, subject)
        return f"""
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

    def implement(self, phase: TddPhase, context: str) -> str:
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
        return f"""
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

    def review(self, index: int, plan: str, test_run: PhaseTestResult) -> str:
        goal = self.spec.describe() if self.spec else self.goal
        return f"""
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

    def follow_up(
        self,
        index: int,
        plan: str,
        review: str,
        test_run: PhaseTestResult,
    ) -> str:
        goal = self.spec.describe() if self.spec else self.goal
        return f"""
あなたは Codex Follow Up 担当です。
今回の RED-GREEN-REFACTOR 後に、要件やテスト観点の抜け漏れを振り返ってください。
実装やファイル編集は絶対にしないでください。

確認すること:
- ゴールや spec に対して、まだ明文化されていない要件がないか
- 今回の実装に対して、追加で RED にすべき境界値、例外系、責務分離のテストがないか
- AI が推定して進めるべきではない仕様判断がないか
- 見つけたものは 1 項目 1 behavior または 1 テスト観点に分ける
- 既に covered なものは重複して返さない

ユーザー判断が必要な場合:
- needs_user_input を true にしてください
- questions_for_user に質問、理由、選択肢、何を block しているかを入れてください
- 質問が必要な項目は missing_requirements に推測で入れないでください

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

    def subject_text(self, index: int, subject: CycleSubject) -> str:
        if subject.requirement_item:
            return self._requirement_text(subject.requirement_item)
        if subject.backlog_item:
            return self._backlog_text(subject.backlog_item)
        if subject.cycle:
            return self._cycle_text(subject.cycle)
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
