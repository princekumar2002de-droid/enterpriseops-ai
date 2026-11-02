"""Command line interface.

    uv run python -m data_generation generate [--seed 42] [--profile full|small]
    uv run python -m data_generation validate

Both use EOPS_DATABASE_URL (from the environment or the repo-root .env).
Exit code 1 if any validation check fails.
"""

import argparse
import sys
import time

from app.core.config import get_settings
from app.db.session import get_engine
from data_generation import GENERATOR_VERSION
from data_generation.generator import content_hash, generate
from data_generation.loader import load
from data_generation.model import PROFILES
from data_generation.validation import validate


def _print_validation() -> int:
    results, summary = validate(get_engine())
    print("\nValidation checks")
    for r in results:
        mark = "PASS" if r.passed else f"FAIL ({r.violations})"
        print(f"  [{mark:>10}] {r.check.group:<10} {r.check.description}")
    for title, rows in summary.items():
        print(f"\n{title}")
        width = max((len(k) for k, _ in rows), default=0)
        for key, value in rows:
            print(f"  {key:<{width}}  {value}")
    failed = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="data_generation",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="generate and load the synthetic dataset")
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--profile", choices=sorted(PROFILES), default="full")
    sub.add_parser("validate", help="run validation checks on the loaded dataset")
    args = parser.parse_args(argv)

    if args.command == "generate":
        started = time.perf_counter()
        dataset = generate(args.seed, PROFILES[args.profile])
        counts = load(get_engine(), dataset, get_settings().environment)
        print(
            f"Generator {GENERATOR_VERSION}: seed={args.seed} profile={args.profile} "
            f"in {time.perf_counter() - started:.1f}s"
        )
        print(
            f"Content hash {content_hash(dataset)[:16]}...  "
            f"({sum(counts.values())} rows in {len(counts)} tables)"
        )
    return _print_validation()


if __name__ == "__main__":
    sys.exit(main())
