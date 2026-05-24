import json
from pathlib import Path

from aitdd.agents import AgentResult
from aitdd.review import PASSING_FOLLOW_UP_JSON, PASSING_REVIEW_JSON
from aitdd.runner import TddLoop, TddLoopConfig


class FakeAgent:
    def __init__(self, role: str, outputs: list[str]) -> None:
        self.role = role
        self.outputs = outputs
        self.prompts: list[str] = []

    def run(self, prompt: str, cwd: Path) -> AgentResult:
        self.prompts.append(prompt)
        output = self.outputs.pop(0) if self.outputs else "{}"
        return AgentResult(self.role, prompt, output, "", 0)


def test_dry_run_loop_uses_codex_for_plan_review_and_cursor_for_implementation(
    tmp_path: Path,
) -> None:
    planner = FakeAgent(
        "codex",
        [
            "write the first failing test",
            PASSING_REVIEW_JSON,
            PASSING_FOLLOW_UP_JSON,
        ],
    )
    implementer = FakeAgent("cursor", ["red ok", "green ok"])
    loop = TddLoop(
        TddLoopConfig(
            goal="build a tiny thing",
            workdir=tmp_path,
            dry_run=True,
            max_cycles=3,
        ),
        planner=planner,
        implementer=implementer,
    )

    results = loop.run()

    assert len(results) == 1
    assert results[0].complete is True
    assert len(planner.prompts) == 3
    assert len(implementer.prompts) == 2
    assert "現在フェーズ: RED" in implementer.prompts[0]
    assert "現在フェーズ: GREEN" in implementer.prompts[1]
    assert (tmp_path / ".aitdd" / "progress.json").exists()
    assert (tmp_path / ".aitdd" / "report.md").exists()


def test_spec_cycle_is_included_in_planning_prompt(tmp_path: Path) -> None:
    spec_path = tmp_path / "aitdd.yaml"
    spec_path.write_text(
        """
goal: Build Money
cycles:
  - behavior: Money stores amount and currency
    expected_red_failure:
      - ModuleNotFoundError
""".strip()
    )
    planner = FakeAgent(
        "codex",
        [
            "plan",
            PASSING_REVIEW_JSON,
            PASSING_FOLLOW_UP_JSON,
        ],
    )
    implementer = FakeAgent("cursor", ["red ok", "green ok"])
    loop = TddLoop(
        TddLoopConfig(
            goal="ignored when spec exists",
            workdir=tmp_path,
            spec_path=spec_path,
            dry_run=True,
            max_cycles=1,
        ),
        planner=planner,
        implementer=implementer,
    )

    loop.run()

    assert "Money stores amount and currency" in planner.prompts[0]
    assert "ModuleNotFoundError" in planner.prompts[0]


def test_review_gate_blocks_non_minimal_green(tmp_path: Path) -> None:
    planner = FakeAgent(
        "codex",
        [
            "plan",
            '{"complete": false, "reason": "too much", "one_behavior_only": true, '
            '"minimal_green": false, "tests_unchanged_in_refactor": true, '
            '"acceptance_unit_boundary_ok": true, "forbidden_respected": true, '
            '"issues": ["implemented behavior without RED"]}',
        ],
    )
    implementer = FakeAgent("cursor", ["red ok", "green ok"])
    loop = TddLoop(
        TddLoopConfig(
            goal="build a tiny thing",
            workdir=tmp_path,
            dry_run=True,
            max_cycles=1,
        ),
        planner=planner,
        implementer=implementer,
    )

    try:
        loop.run()
    except RuntimeError as exc:
        assert "minimal_green=false" in str(exc)
        assert "implemented behavior without RED" in str(exc)
    else:
        raise AssertionError("review gate should fail")


def test_missing_test_perspectives_become_next_red_cycle(tmp_path: Path) -> None:
    missing_review = (
        '{"complete": true, "reason": "cycle ok but boundary test is missing", '
        '"one_behavior_only": true, "minimal_green": true, '
        '"tests_unchanged_in_refactor": true, "acceptance_unit_boundary_ok": true, '
        '"forbidden_respected": true, "issues": [], "needs_more_tests": true, '
        '"missing_test_perspectives": ['
        '{"behavior": "zero amount is valid", '
        '"reason": "boundary value is not fixed", '
        '"suggested_test": "Money(0, \\"USD\\") is accepted", '
        '"priority": "high"}]}'
    )
    planner = FakeAgent(
        "codex",
        [
            "plan initial behavior",
            missing_review,
            PASSING_FOLLOW_UP_JSON,
            "plan zero amount boundary",
            PASSING_REVIEW_JSON,
            PASSING_FOLLOW_UP_JSON,
        ],
    )
    implementer = FakeAgent(
        "cursor",
        ["red ok", "green ok", "refactor ok", "red ok", "green ok"],
    )
    loop = TddLoop(
        TddLoopConfig(
            goal="build Money",
            workdir=tmp_path,
            dry_run=True,
            max_cycles=3,
        ),
        planner=planner,
        implementer=implementer,
    )

    results = loop.run()

    assert len(results) == 2
    assert "zero amount is valid" in planner.prompts[2]
    progress = json.loads((tmp_path / ".aitdd" / "progress.json").read_text())
    assert progress["cycles"][1]["source"] == "test_backlog"
    assert progress["test_backlog"][0]["status"] == "completed"


def test_follow_up_missing_requirement_becomes_next_red_cycle(tmp_path: Path) -> None:
    missing_requirement = (
        '{"requirements_sufficient": false, "needs_more_requirements": true, '
        '"needs_more_tests": false, "missing_requirements": ['
        '{"requirement": "currency must be non-empty", '
        '"reason": "invalid currency values are not specified", '
        '"suggested_behavior": "empty currency is rejected", '
        '"priority": "high"}], '
        '"additional_test_perspectives": [], "notes": []}'
    )
    planner = FakeAgent(
        "codex",
        [
            "plan initial behavior",
            PASSING_REVIEW_JSON,
            missing_requirement,
            "plan empty currency requirement",
            PASSING_REVIEW_JSON,
            PASSING_FOLLOW_UP_JSON,
        ],
    )
    implementer = FakeAgent("cursor", ["red ok", "green ok", "red ok", "green ok"])
    loop = TddLoop(
        TddLoopConfig(
            goal="build Money",
            workdir=tmp_path,
            dry_run=True,
            max_cycles=3,
        ),
        planner=planner,
        implementer=implementer,
    )

    results = loop.run()

    assert len(results) == 2
    assert "empty currency is rejected" in planner.prompts[3]
    progress = json.loads((tmp_path / ".aitdd" / "progress.json").read_text())
    assert progress["cycles"][1]["source"] == "requirements_backlog"
    assert progress["requirements_backlog"][0]["status"] == "completed"
