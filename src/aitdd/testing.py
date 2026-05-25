"""Workspace test execution and refactor guards."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .hook_policy import PhaseTestResult


class WorkspaceTester:
    def __init__(self, workdir: Path, test_command: str) -> None:
        self.workdir = workdir
        self.test_command = test_command

    def run_tests(self) -> PhaseTestResult:
        return self.run_command(self.test_command)

    def run_command(self, command: str) -> PhaseTestResult:
        completed = subprocess.run(
            command,
            cwd=self.workdir,
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

    def snapshot_test_files(self) -> dict[Path, str]:
        snapshots: dict[Path, str] = {}
        for path in self.workdir.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.name.startswith("test_") or path.parent.name in {"tests", "test"}:
                snapshots[path.relative_to(self.workdir)] = path.read_text(errors="ignore")
        return snapshots

    def require_refactor_kept_tests(self, before: dict[Path, str]) -> None:
        after = self.snapshot_test_files()
        if before != after:
            raise RuntimeError("REFACTOR rejected: test files changed during refactor phase.")
