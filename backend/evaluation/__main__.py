"""Evaluation command line.

    uv run python -m evaluation matching --seed 42 [--profile full] [--report PATH]
        Generate the dataset in memory, run the engine, score it against the labels.
    uv run python -m evaluation tune-duplicates --seed 7
        Duplicate threshold sweep on a tuning seed (never the reporting seed - decision D2).
    uv run python -m evaluation db
        Score the latest matching run in the database against the loaded labels.

Exit code 1 if a Task 3 target (decision D3) is missed.
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.db import tables as t
from app.db.session import get_engine
from app.services.matching.duplicates import DuplicateConfig
from app.services.matching.engine import ENGINE_VERSION
from app.services.matching.repository import latest_run_id
from data_generation import GENERATOR_VERSION
from data_generation.generator import content_hash, generate
from data_generation.model import PROFILES
from evaluation.matching_eval import (
    EvaluationReport,
    Key,
    evaluate_keys,
    evaluate_tables,
    render_markdown,
    sweep_duplicate_threshold,
)


def _print(report: EvaluationReport) -> int:
    for m in report.per_code:
        print(
            f"  {m.code:<26} tp={m.tp:<5} fp={m.fp:<4} fn={m.fn:<4} "
            f"P={m.precision:.3f} R={m.recall:.3f}"
        )
    print(
        f"  look-alike invoices flagged: {report.hard_negative_false_positives}"
        f"/{report.hard_negative_invoices} ({report.hard_negative_fp_rate:.2%})"
    )
    missed = 0
    for name, (value, target, ok) in report.target_checks().items():
        print(f"  [{'PASS' if ok else 'MISS'}] {name:<24} {value:.3f} (target {target})")
        missed += not ok
    return 1 if missed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evaluation", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("matching")
    m.add_argument("--seed", type=int, default=42)
    m.add_argument("--profile", choices=sorted(PROFILES), default="full")
    m.add_argument("--report", type=Path, default=None, help="write a Markdown report")
    tune = sub.add_parser("tune-duplicates")
    tune.add_argument("--seed", type=int, default=7)
    sub.add_parser("db")
    args = parser.parse_args(argv)

    if args.command == "tune-duplicates":
        dataset = generate(args.seed, PROFILES["full"])
        print(
            f"Duplicate threshold sweep on tuning seed {args.seed} "
            f"(current default {DuplicateConfig().threshold}):"
        )
        thresholds = [Decimal(x) / 100 for x in range(30, 101, 5)]
        for th, met in sweep_duplicate_threshold(dataset.tables, dataset.labels, thresholds):
            print(
                f"  {th:.2f}  tp={met.tp:<3} fp={met.fp:<4} fn={met.fn:<3} "
                f"P={met.precision:.3f} R={met.recall:.3f}"
            )
        return 0

    if args.command == "matching":
        dataset = generate(args.seed, PROFILES[args.profile])
        _, report = evaluate_tables(dataset.tables, dataset.labels)
        print(f"Engine {ENGINE_VERSION} on seed {args.seed} ({args.profile}):")
        code = _print(report)
        if args.report:
            context = {
                "Engine version": ENGINE_VERSION,
                "Dataset": f"generator {GENERATOR_VERSION}, seed {args.seed}, "
                f"profile {args.profile}, "
                f"content hash `{content_hash(dataset)[:16]}...`",
                "Duplicate threshold": f"{DuplicateConfig().threshold} (tuned on seed 7)",
            }
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(render_markdown("Matching engine evaluation", report, context))
            print(f"Report written to {args.report}")
        return code

    with get_engine().connect() as conn:  # db
        run_id = latest_run_id(conn)
        if run_id is None:
            print("No completed match run - run `uv run python -m app.services.matching` first.")
            return 1
        found: set[Key] = {
            (r.invoice_id, r.item_no, r.code)
            for r in conn.execute(
                select(t.exception.c.invoice_id, t.exception.c.item_no, t.exception.c.code).where(
                    t.exception.c.run_id == run_id
                )
            )
        }
        labels = [dict(r) for r in conn.execute(select(t.ground_truth_label)).mappings()]
    print(f"Match run {run_id} vs ground truth in the database:")
    return _print(evaluate_keys(found, labels))


if __name__ == "__main__":
    sys.exit(main())
