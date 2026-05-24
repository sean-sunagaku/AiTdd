"""Minimal persistent progress and report files."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .hook_policy import PhaseTestResult
from .review import ReviewGate


@dataclass
class CycleProgress:
    index: int
    behavior: str
    source: str = "codex"
    backlog_item_id: str | None = None
    status: str = "started"
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    red: dict[str, Any] | None = None
    green: dict[str, Any] | None = None
    refactor: dict[str, Any] | None = None
    review_gate: dict[str, Any] | None = None
    issues: list[str] = field(default_factory=list)


class ProgressStore:
    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.root = workdir / ".aitdd"
        self.cycles_dir = self.root / "cycles"
        self.progress_path = self.root / "progress.json"
        self.report_path = self.root / "report.md"
        self.root.mkdir(exist_ok=True)
        self.cycles_dir.mkdir(exist_ok=True)
        self.data = self._load()

    def start_cycle(
        self,
        index: int,
        behavior: str,
        plan: str,
        source: str = "codex",
        backlog_item_id: str | None = None,
    ) -> CycleProgress:
        cycle = CycleProgress(
            index=index,
            behavior=behavior,
            source=source,
            backlog_item_id=backlog_item_id,
        )
        self._upsert(cycle)
        self.append_report(f"## Cycle {index}: {behavior}\n\n### Plan\n\n{plan}\n")
        return cycle

    def record_phase(self, cycle: CycleProgress, phase: str, result: PhaseTestResult) -> None:
        setattr(cycle, phase, _phase_dict(result))
        self.snapshot_diff(cycle.index, phase)
        self._upsert(cycle)
        self.append_report(
            f"\n### {phase.upper()}\n\n"
            f"- command: `{result.command}`\n"
            f"- returncode: `{result.returncode}`\n"
        )

    def record_review(self, cycle: CycleProgress, review_gate: ReviewGate) -> None:
        cycle.review_gate = asdict(review_gate)
        cycle.issues = review_gate.issues
        self._upsert(cycle)
        self._record_missing_test_perspectives(cycle.index, review_gate)
        self.append_report(
            "\n### Review Gate\n\n"
            f"- one_behavior_only: `{review_gate.one_behavior_only}`\n"
            f"- minimal_green: `{review_gate.minimal_green}`\n"
            f"- tests_unchanged_in_refactor: `{review_gate.tests_unchanged_in_refactor}`\n"
            f"- acceptance_unit_boundary_ok: `{review_gate.acceptance_unit_boundary_ok}`\n"
            f"- forbidden_respected: `{review_gate.forbidden_respected}`\n"
            f"- needs_more_tests: `{review_gate.needs_more_tests}`\n"
            f"- issues: `{', '.join(review_gate.issues) if review_gate.issues else 'none'}`\n"
        )
        if review_gate.missing_test_perspectives:
            body = "\n".join(
                f"- `{item.priority}` {item.behavior}: {item.suggested_test}"
                for item in review_gate.missing_test_perspectives
            )
            self.append_report(f"\n### Missing Test Perspectives\n\n{body}\n")

    def finish_cycle(self, cycle: CycleProgress, status: str) -> None:
        cycle.status = status
        cycle.finished_at = datetime.now(UTC).isoformat()
        self._upsert(cycle)
        if cycle.backlog_item_id and status == "completed":
            self.complete_test_perspective(cycle.backlog_item_id)
        self.append_report(f"\n### Result\n\n`{status}`\n")

    def fail_cycle(self, cycle: CycleProgress | None, error: BaseException) -> None:
        if cycle is None:
            self.data["last_error"] = str(error)
            self._write()
            self.append_report(f"\n## Failure\n\n{error}\n")
            return
        cycle.status = "failed"
        cycle.finished_at = datetime.now(UTC).isoformat()
        cycle.issues.append(str(error))
        self._upsert(cycle)
        self.append_report(f"\n### Failure\n\n{error}\n")

    def next_cycle_index(self) -> int:
        cycles = self.data.get("cycles", [])
        for item in cycles:
            if item.get("status") != "completed":
                return int(item.get("index", 1))
        return len(cycles) + 1

    def completed_spec_cycle_count(self) -> int:
        return sum(
            1
            for item in self.data.get("cycles", [])
            if item.get("source") == "spec" and item.get("status") == "completed"
        )

    def pending_test_perspectives(self) -> list[dict[str, Any]]:
        return [
            item
            for item in self.data.get("test_backlog", [])
            if item.get("status") == "pending"
        ]

    def has_pending_test_backlog(self) -> bool:
        return bool(self.pending_test_perspectives())

    def claim_next_test_perspective(self, cycle_index: int) -> dict[str, Any] | None:
        for item in self.data.get("test_backlog", []):
            if item.get("status") != "pending":
                continue
            item["status"] = "in_progress"
            item["planned_cycle"] = cycle_index
            item["planned_at"] = datetime.now(UTC).isoformat()
            self._write()
            return item
        return None

    def complete_test_perspective(self, item_id: str) -> None:
        for item in self.data.get("test_backlog", []):
            if item.get("id") != item_id:
                continue
            item["status"] = "completed"
            item["completed_at"] = datetime.now(UTC).isoformat()
            self._write()
            return

    def snapshot_diff(self, index: int, phase: str) -> None:
        path = self.cycles_dir / f"{index:03d}-{phase}.diff"
        diff = _git_diff(self.workdir)
        path.write_text(diff or "# No git diff available.\n")

    def append_report(self, text: str) -> None:
        if not self.report_path.exists():
            self.report_path.write_text("# AiTdd Report\n")
        with self.report_path.open("a") as stream:
            stream.write(text)
            if not text.endswith("\n"):
                stream.write("\n")

    def _load(self) -> dict[str, Any]:
        if not self.progress_path.exists():
            return {"cycles": [], "test_backlog": []}
        data = json.loads(self.progress_path.read_text())
        data.setdefault("cycles", [])
        data.setdefault("test_backlog", [])
        return data

    def _record_missing_test_perspectives(
        self,
        source_cycle: int,
        review_gate: ReviewGate,
    ) -> None:
        if not review_gate.missing_test_perspectives:
            return

        backlog = self.data.setdefault("test_backlog", [])
        existing = {_test_perspective_key(item) for item in backlog}
        for perspective in review_gate.missing_test_perspectives:
            item = asdict(perspective)
            if not item["behavior"] or not item["suggested_test"]:
                continue
            key = _test_perspective_key(item)
            if key in existing:
                continue
            item.update(
                {
                    "id": f"{source_cycle:03d}-{len(backlog) + 1:03d}",
                    "status": "pending",
                    "source_cycle": source_cycle,
                    "discovered_at": datetime.now(UTC).isoformat(),
                }
            )
            backlog.append(item)
            existing.add(key)
        self._write()

    def _upsert(self, cycle: CycleProgress) -> None:
        cycles = [item for item in self.data.get("cycles", []) if item.get("index") != cycle.index]
        cycles.append(asdict(cycle))
        cycles.sort(key=lambda item: item["index"])
        self.data["cycles"] = cycles
        self._write()

    def _write(self) -> None:
        self.progress_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")


def _phase_dict(result: PhaseTestResult) -> dict[str, Any]:
    return {
        "command": result.command,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }


def _git_diff(workdir: Path) -> str:
    in_git = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", "--is-inside-work-tree"],
        text=True,
        capture_output=True,
        check=False,
    )
    if in_git.returncode != 0:
        return ""

    tracked = subprocess.run(
        ["git", "-C", str(workdir), "diff", "--binary", "--no-ext-diff"],
        text=True,
        capture_output=True,
        check=False,
    )
    diff = tracked.stdout
    untracked = subprocess.run(
        ["git", "-C", str(workdir), "ls-files", "--others", "--exclude-standard"],
        text=True,
        capture_output=True,
        check=False,
    )
    for relative in untracked.stdout.splitlines():
        file_diff = subprocess.run(
            ["git", "-C", str(workdir), "diff", "--no-index", "--", "/dev/null", relative],
            text=True,
            capture_output=True,
            check=False,
        )
        diff += file_diff.stdout
    return diff


def _test_perspective_key(item: dict[str, Any]) -> tuple[str, str]:
    return (
        str(item.get("behavior") or "").strip().lower(),
        str(item.get("suggested_test") or "").strip().lower(),
    )
