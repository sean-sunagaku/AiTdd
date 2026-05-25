"""Compatibility facade for the CLI interface."""

from .interfaces.cli import *  # noqa: F403
from .interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

