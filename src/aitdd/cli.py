"""Command line entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from .planning import draft_spec_yaml
from .runner import TddLoop, TddLoopConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aitdd")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run the Codex/Cursor TDD loop")
    _add_run_arguments(run)

    resume = subparsers.add_parser("resume", help="resume from .aitdd/progress.json")
    _add_run_arguments(resume)
    resume.set_defaults(resume=True)

    plan = subparsers.add_parser("plan", help="draft an aitdd.yaml spec with Codex")
    plan.add_argument("goal")
    plan.add_argument("--workdir", default=".")
    plan.add_argument("--output", type=Path, default=Path("aitdd.yaml"))
    plan.add_argument("--codex-model")
    plan.add_argument("--dry-run", action="store_true")
    plan.add_argument("--force", action="store_true", help="overwrite an existing output file")
    return parser


def _add_run_arguments(run: argparse.ArgumentParser) -> None:
    run.add_argument("goal", nargs="?", default="")
    run.add_argument("--workdir", default=".")
    run.add_argument("--test-command", default="pytest")
    run.add_argument("--max-cycles", type=int, default=5)
    run.add_argument("--spec", type=Path, help="path to aitdd.yaml")
    run.add_argument("--codex-model")
    run.add_argument("--cursor-model", default="composer-latest")
    run.add_argument(
        "--cursor-backend",
        choices=["cli", "sdk"],
        default="sdk",
        help="use cursor-agent CLI or the official @cursor/sdk bridge",
    )
    run.add_argument("--dry-run", action="store_true")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {"run", "resume"}:
        if not args.goal and not args.spec:
            raise SystemExit("goal is required unless --spec is provided")
        config = TddLoopConfig(
            goal=args.goal,
            workdir=Path(args.workdir).resolve(),
            test_command=args.test_command,
            max_cycles=args.max_cycles,
            spec_path=args.spec.resolve() if args.spec else None,
            codex_model=args.codex_model,
            cursor_model=args.cursor_model,
            cursor_backend=args.cursor_backend,
            resume=getattr(args, "resume", False),
            dry_run=args.dry_run,
        )
        results = TddLoop(config).run()
        for result in results:
            print(
                f"cycle={result.index} red={result.red.returncode} "
                f"green={result.green.returncode} refactor={result.refactor.returncode} "
                f"complete={result.complete} "
                f"one_behavior_only={result.review_gate.one_behavior_only} "
                f"minimal_green={result.review_gate.minimal_green} "
                f"boundary_ok={result.review_gate.acceptance_unit_boundary_ok}"
            )
        return 0
    if args.command == "plan":
        workdir = Path(args.workdir).resolve()
        output = args.output if args.output.is_absolute() else workdir / args.output
        if output.exists() and not args.force:
            raise SystemExit(f"{output} already exists. Use --force to overwrite it.")
        text = draft_spec_yaml(
            args.goal,
            workdir=workdir,
            codex_model=args.codex_model,
            dry_run=args.dry_run,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
        print(f"wrote {output}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
