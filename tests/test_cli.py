from pathlib import Path

import pytest

from aitdd.cli import main
from aitdd.spec import AitddSpec


def test_plan_dry_run_writes_valid_spec(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "aitdd.yaml"

    result = main(
        [
            "plan",
            "Build a Money class",
            "--workdir",
            str(tmp_path),
            "--output",
            str(output),
            "--dry-run",
        ]
    )

    assert result == 0
    spec = AitddSpec.from_file(output)
    assert spec.goal == "Build a Money class"
    assert spec.cycles[0].behavior == "first observable behavior for Build a Money class"
    assert str(output) in capsys.readouterr().out


def test_plan_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    output = tmp_path / "aitdd.yaml"
    output.write_text("goal: keep me\n")

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "plan",
                "Build a Money class",
                "--workdir",
                str(tmp_path),
                "--output",
                str(output),
                "--dry-run",
            ]
        )

    assert "already exists" in str(exc.value)
    assert output.read_text() == "goal: keep me\n"
