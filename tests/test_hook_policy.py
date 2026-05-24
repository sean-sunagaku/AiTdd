from aitdd.hook_policy import PhaseTestResult, TddPhase, evaluate_phase


def test_red_requires_failing_tests() -> None:
    assert evaluate_phase(TddPhase.RED, PhaseTestResult("pytest", 1)).allowed
    assert evaluate_phase(TddPhase.RED, PhaseTestResult("pytest", 0)).denied


def test_red_requires_expected_failure_when_specified() -> None:
    accepted = evaluate_phase(
        TddPhase.RED,
        PhaseTestResult("pytest", 1, stderr="ModuleNotFoundError: No module named money"),
        ["ModuleNotFoundError"],
    )
    rejected = evaluate_phase(
        TddPhase.RED,
        PhaseTestResult("pytest", 1, stderr="SyntaxError: invalid syntax"),
        ["ModuleNotFoundError"],
    )

    assert accepted.allowed
    assert rejected.denied


def test_green_and_refactor_require_passing_tests() -> None:
    assert evaluate_phase(TddPhase.GREEN, PhaseTestResult("pytest", 0)).allowed
    assert evaluate_phase(TddPhase.GREEN, PhaseTestResult("pytest", 1)).denied
    assert evaluate_phase(TddPhase.REFACTOR, PhaseTestResult("pytest", 0)).allowed
    assert evaluate_phase(TddPhase.REFACTOR, PhaseTestResult("pytest", 1)).denied
