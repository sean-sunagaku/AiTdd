from pathlib import Path

from aitdd.agents import AgentResult
from aitdd.planning import draft_spec_yaml
from aitdd.spec import AitddSpec


class FakePlanner:
    role = "codex"

    def run(
        self,
        prompt: str,
        cwd: Path,
        output_schema: dict[str, object] | None = None,
    ) -> AgentResult:
        assert output_schema is not None
        return AgentResult(
            self.role,
            prompt,
            """
            {
              "goal": "Build Money",
              "constraints": ["one behavior per cycle"],
              "public_api": ["Money(amount, currency)"],
              "forbidden": ["untested behavior"],
              "acceptance_tests": ["workflows/test_money.py"],
              "unit_tests": ["tests/test_money.py"],
              "done_when": ["all_cycles_complete", "acceptance_tests_pass"],
              "acceptance_test_command": "pytest workflows",
              "cycles": [
                {
                  "behavior": "Money stores amount",
                  "notes": ["start from the smallest RED"],
                  "expected_red": {
                    "exit_code": "nonzero",
                    "must_include": ["ModuleNotFoundError"],
                    "must_not_include": ["SyntaxError"]
                  }
                }
              ]
            }
            """,
            "",
            0,
        )


def test_draft_spec_yaml_uses_codex_json_schema_output(tmp_path: Path) -> None:
    path = tmp_path / "aitdd.yaml"

    path.write_text(draft_spec_yaml("Build Money", tmp_path, planner=FakePlanner()))

    spec = AitddSpec.from_file(path)
    assert spec.goal == "Build Money"
    assert spec.acceptance_test_command == "pytest workflows"
    assert spec.cycles[0].expected_red_failure is not None
    assert spec.cycles[0].expected_red_failure.must_not_include == ["SyntaxError"]
