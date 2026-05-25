#!/usr/bin/env python3
"""Codex PostToolUse hook that enforces the active TDD phase."""

from __future__ import annotations

import os
import subprocess

from codex_hookkit import PostToolUseInput, PostToolUseOutput, deny

from aitdd.domain.policy import PhaseTestResult, TddPhase, evaluate_phase


def main() -> int:
    try:
        payload = PostToolUseInput.from_stdin()
    except Exception as exc:
        return deny.stderr_exit(f"Invalid Codex hook payload: {exc}")

    phase_name = os.environ.get("AITDD_PHASE")
    if not phase_name:
        PostToolUseOutput.minimal().write()
        return 0

    try:
        phase = TddPhase(phase_name.lower())
    except ValueError:
        return deny.stderr_exit(f"Invalid AITDD_PHASE: {phase_name}")

    command = os.environ.get("AITDD_TEST_COMMAND", "pytest")
    completed = subprocess.run(
        command,
        cwd=payload.cwd,
        shell=True,
        text=True,
        capture_output=True,
        check=False,
    )
    decision = evaluate_phase(
        phase,
        PhaseTestResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        ),
    )
    if decision.denied:
        return deny.stderr_exit(decision.reason)

    PostToolUseOutput.minimal().write()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
