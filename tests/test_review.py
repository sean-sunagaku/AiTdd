from aitdd.review import FollowUpReview, ReviewGate


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


def test_follow_up_review_parses_missing_requirements_and_tests() -> None:
    follow_up = FollowUpReview.from_text(
        """
        {
          "requirements_sufficient": false,
          "needs_more_requirements": true,
          "needs_more_tests": true,
          "missing_requirements": [
            {
              "requirement": "currency must be non-empty",
              "reason": "invalid currency values are not specified",
              "suggested_behavior": "empty currency is rejected",
              "priority": "high"
            }
          ],
          "additional_test_perspectives": [
            {
              "behavior": "amount upper bound",
              "reason": "large amount is not covered",
              "suggested_test": "Money can store a large amount",
              "priority": "low"
            }
          ],
          "notes": ["follow up needed"]
        }
        """
    )

    assert follow_up.needs_more_work
    assert follow_up.missing_requirements[0].suggested_behavior == "empty currency is rejected"
    assert follow_up.additional_test_perspectives[0].behavior == "amount upper bound"
