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
          "issues": ["extra behavior was implemented"],
          "needs_more_tests": true,
          "missing_test_perspectives": [
            {
              "behavior": "zero amount is valid",
              "reason": "boundary value is not fixed",
              "suggested_test": "Money(0, 'USD') is accepted",
              "priority": "high"
            }
          ]
        }
        """
    )

    assert not gate.passed
    assert gate.needs_more_tests
    assert gate.missing_test_perspectives[0].behavior == "zero amount is valid"
    assert "minimal_green=false" in gate.failure_message()
    assert "extra behavior was implemented" in gate.failure_message()
