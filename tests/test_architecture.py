import importlib
import importlib.util
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


def test_legacy_facade_modules_are_removed() -> None:
    removed_modules = [
        "aitdd.agents",
        "aitdd.cli",
        "aitdd.decision",
        "aitdd.hook_policy",
        "aitdd.planning",
        "aitdd.progress",
        "aitdd.prompts",
        "aitdd.review",
        "aitdd.runner",
        "aitdd.spec",
        "aitdd.subjects",
        "aitdd.testing",
    ]

    for module in removed_modules:
        assert importlib.util.find_spec(module) is None


def test_architecture_doc_names_ddd_layers() -> None:
    text = Path("docs/architecture.md").read_text()

    assert "domain/" in text
    assert "application/" in text
    assert "infrastructure/" in text
    assert "interfaces/" in text
