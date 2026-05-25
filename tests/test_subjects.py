from pathlib import Path

from aitdd.application.subjects import CycleSubjectSelector
from aitdd.domain.spec import AitddSpec
from aitdd.infrastructure.progress import ProgressStore


def test_cycle_subject_selector_prioritizes_requirement_backlog(tmp_path: Path) -> None:
    progress = ProgressStore(tmp_path)
    progress.data["requirements_backlog"] = [
        {
            "id": "req-001",
            "status": "pending",
            "requirement": "currency must be non-empty",
            "suggested_behavior": "empty currency is rejected",
        }
    ]

    subject = CycleSubjectSelector(progress).select(1)

    assert subject.source == "requirements_backlog"
    assert subject.behavior == "empty currency is rejected"
    assert subject.backlog_item_id == "req-001"


def test_cycle_subject_selector_uses_spec_after_backlog(tmp_path: Path) -> None:
    spec_path = tmp_path / "aitdd.yaml"
    spec_path.write_text(
        """
goal: Build Money
cycles:
  - behavior: Money stores amount
""".strip()
    )
    progress = ProgressStore(tmp_path)
    spec = AitddSpec.from_file(spec_path)

    subject = CycleSubjectSelector(progress, spec).select(1)

    assert subject.source == "spec"
    assert subject.behavior == "Money stores amount"
    assert subject.cycle is spec.cycles[0]
