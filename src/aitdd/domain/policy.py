"""TDD phase policy shared by the loop and Codex hooks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from codex_hookkit import Decision, allow, deny


class TddPhase(str, Enum):
    RED = "red"
    GREEN = "green"
    REFACTOR = "refactor"


@dataclass(frozen=True)
class PhaseTestResult:
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    @property
    def failed(self) -> bool:
        return not self.passed


@dataclass(frozen=True)
class ExpectedRed:
    exit_code: str = "nonzero"
    must_include: list[str] | None = None
    must_not_include: list[str] | None = None


def evaluate_phase(
    phase: TddPhase,
    test_run: PhaseTestResult,
    expected_red_failure: list[str] | ExpectedRed | None = None,
) -> Decision:
    if phase is TddPhase.RED:
        if test_run.passed:
            return deny.decision(
                "RED rejected: tests passed. Add the smallest meaningful failing test first."
            )

        expected = _normalize_expected_red(expected_red_failure)
        if not expected:
            return allow.decision("RED accepted: tests fail as expected.")

        combined_output = f"{test_run.stdout}\n{test_run.stderr}"
        forbidden = expected.must_not_include or []
        if any(fragment in combined_output for fragment in forbidden):
            return deny.decision(
                "RED rejected: tests failed with a forbidden reason. "
                f"Forbidden: {', '.join(forbidden)}"
            )

        required = expected.must_include or []
        if not required or any(fragment in combined_output for fragment in required):
            return allow.decision("RED accepted: tests fail for the expected reason.")
        return deny.decision(
            "RED rejected: tests failed, but not for the expected reason. "
            f"Expected one of: {', '.join(required)}"
        )

    if test_run.passed:
        return allow.decision(f"{phase.value.upper()} accepted: tests pass.")

    return deny.decision(
        f"{phase.value.upper()} rejected: tests are failing. "
        "Restore a passing suite before moving on."
    )


def _normalize_expected_red(value: list[str] | ExpectedRed | None) -> ExpectedRed | None:
    if value is None:
        return None
    if isinstance(value, ExpectedRed):
        return value
    return ExpectedRed(must_include=value)
