"""Pure cycle concepts shared by application services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CycleStatus:
    value: str


STARTED = CycleStatus("started")
COMPLETED = CycleStatus("completed")
FAILED = CycleStatus("failed")
NEEDS_USER_INPUT = CycleStatus("needs_user_input")

__all__ = ["COMPLETED", "FAILED", "NEEDS_USER_INPUT", "STARTED", "CycleStatus"]
