from aitdd.review import ReviewGate


def test_review_gate_parses_and_reports_failures() -> None:
    gate = ReviewGate.from_text(
        """
        {
          "complete": false,
          "reason": "green was too broad",
          "one_behavior_only": true,
          "minimal_green": false,
          "tests_unchanged_in_refactor": true,
          "acceptance_unit_boundary_ok": true,
          "forbidden_respected": true,
          "issues": ["extra behavior was implemented"]
        }
        """
    )

    assert not gate.passed
    assert "minimal_green=false" in gate.failure_message()
    assert "extra behavior was implemented" in gate.failure_message()
