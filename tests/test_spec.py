from pathlib import Path

from aitdd.spec import AitddSpec


def test_spec_loads_cycles_and_expected_red_failures(tmp_path: Path) -> None:
    path = tmp_path / "aitdd.yaml"
    path.write_text(
        """
goal: Build Money
public_api:
  - Money(amount, currency)
cycles:
  - behavior: Money stores amount
    expected_red_failure:
      - ModuleNotFoundError
""".strip()
    )

    spec = AitddSpec.from_file(path)

    assert spec.goal == "Build Money"
    assert spec.public_api == ["Money(amount, currency)"]
    assert spec.cycles[0].behavior == "Money stores amount"
    assert spec.cycles[0].expected_red_failure is not None
    assert spec.cycles[0].expected_red_failure.must_include == ["ModuleNotFoundError"]


def test_self_dogfood_spec_is_valid() -> None:
    spec = AitddSpec.from_file(Path("examples/aitdd-self.yaml"))

    assert "AiTDD 自身" in spec.goal
    assert "acceptance_tests_pass" in spec.done_when
    assert spec.cycles[0].behavior.startswith("plan subcommand")
