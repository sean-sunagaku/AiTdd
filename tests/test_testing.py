from pathlib import Path

from aitdd.testing import WorkspaceTester


def test_workspace_tester_runs_command(tmp_path: Path) -> None:
    result = WorkspaceTester(tmp_path, "python -c 'print(42)'").run_tests()

    assert result.passed
    assert "42" in result.stdout


def test_workspace_tester_detects_refactor_test_changes(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_money.py"
    test_file.write_text("def test_money():\n    assert True\n")
    tester = WorkspaceTester(tmp_path, "pytest")

    before = tester.snapshot_test_files()
    test_file.write_text("def test_money():\n    assert False\n")

    try:
        tester.require_refactor_kept_tests(before)
    except RuntimeError as exc:
        assert "test files changed" in str(exc)
    else:
        raise AssertionError("refactor guard should reject changed tests")
