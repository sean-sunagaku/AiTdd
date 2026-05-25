import importlib
from pathlib import Path


def test_ddd_package_layout_exists() -> None:
    modules = [
        "aitdd.domain.policy",
        "aitdd.domain.review",
        "aitdd.domain.spec",
        "aitdd.domain.cycle",
        "aitdd.application.loop",
        "aitdd.application.subjects",
        "aitdd.application.decision",
        "aitdd.application.prompts",
        "aitdd.application.planning",
        "aitdd.infrastructure.agents",
        "aitdd.infrastructure.progress",
        "aitdd.infrastructure.testing",
        "aitdd.interfaces.cli",
    ]

    for module in modules:
        importlib.import_module(module)


def test_legacy_imports_remain_as_compatibility_facades() -> None:
    from aitdd.review import ReviewGate
    from aitdd.runner import TddLoop
    from aitdd.spec import AitddSpec

    assert TddLoop.__module__ == "aitdd.application.loop"
    assert ReviewGate.__module__ == "aitdd.domain.review"
    assert AitddSpec.__module__ == "aitdd.domain.spec"


def test_architecture_doc_names_ddd_layers() -> None:
    text = Path("docs/architecture.md").read_text()

    assert "domain/" in text
    assert "application/" in text
    assert "infrastructure/" in text
    assert "interfaces/" in text
