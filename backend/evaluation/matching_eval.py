"""Matching engine evaluation against ground-truth labels.

Unit of comparison: (invoice_id, item_no, code); invoice-level codes use item_no None.
  * true positive  - engine exception that matches a label
  * false positive - engine exception without a matching label
  * false negative - label (not hard negative) the engine missed
Hard negatives: invoices carrying only HN_* labels must produce NO exception at all;
any exception on them counts toward the hard-negative false-positive rate.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.services.matching.duplicates import DuplicateConfig
from app.services.matching.engine import MatchConfig, MatchOutcome, run_matching
from app.services.matching.snapshot import Snapshot

Key = tuple[str, int | None, str]

# Targets agreed for Task 3 (decision D3).
TARGETS = {
    "rule_precision": 0.99,
    "rule_recall": 0.99,
    "duplicate_recall": 0.95,
    "duplicate_precision": 0.85,
    "hard_negative_fp_rate": 0.01,
}


@dataclass(frozen=True)
class CodeMetrics:
    code: str
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0


@dataclass
class EvaluationReport:
    per_code: list[CodeMetrics]
    hard_negative_invoices: int
    hard_negative_false_positives: int
    false_positive_examples: list[Key] = field(default_factory=list)
    false_negative_examples: list[Key] = field(default_factory=list)

    @property
    def hard_negative_fp_rate(self) -> float:
        if not self.hard_negative_invoices:
            return 0.0
        return self.hard_negative_false_positives / self.hard_negative_invoices

    def metrics(self, code: str) -> CodeMetrics:
        return next(m for m in self.per_code if m.code == code)

    def totals(self, exclude: set[str]) -> CodeMetrics:
        rows = [m for m in self.per_code if m.code not in exclude]
        return CodeMetrics(
            "ALL", sum(m.tp for m in rows), sum(m.fp for m in rows), sum(m.fn for m in rows)
        )

    def target_checks(self) -> dict[str, tuple[float, float, bool]]:
        """name -> (value, target, passed)."""
        rule = self.totals(exclude={"DUPLICATE_SUSPECTED"})
        dup = self.metrics("DUPLICATE_SUSPECTED")
        values = {
            "rule_precision": rule.precision,
            "rule_recall": rule.recall,
            "duplicate_recall": dup.recall,
            "duplicate_precision": dup.precision,
            "hard_negative_fp_rate": self.hard_negative_fp_rate,
        }
        out = {}
        for name, value in values.items():
            target = TARGETS[name]
            ok = value <= target if name.endswith("fp_rate") else value >= target
            out[name] = (value, target, ok)
        return out


def evaluate(outcome: MatchOutcome, labels: Iterable[Mapping[str, Any]]) -> EvaluationReport:
    found: set[Key] = {(e.invoice_id, e.item_no, e.code) for e in outcome.exceptions}
    return evaluate_keys(found, labels)


def evaluate_keys(found: set[Key], labels: Iterable[Mapping[str, Any]]) -> EvaluationReport:
    expected: set[Key] = set()
    hn_invoices: set[str] = set()
    real_invoices: set[str] = set()
    for lb in labels:
        if lb["is_hard_negative"]:
            hn_invoices.add(lb["invoice_id"])
        else:
            expected.add((lb["invoice_id"], lb["item_no"], lb["label_code"]))
            real_invoices.add(lb["invoice_id"])

    codes = sorted({k[2] for k in expected | found})
    per_code = []
    for code in codes:
        exp = {k for k in expected if k[2] == code}
        got = {k for k in found if k[2] == code}
        per_code.append(CodeMetrics(code, len(exp & got), len(got - exp), len(exp - got)))

    pure_hn = hn_invoices - real_invoices
    flagged_invoices = {k[0] for k in found}
    return EvaluationReport(
        per_code=per_code,
        hard_negative_invoices=len(pure_hn),
        hard_negative_false_positives=len(pure_hn & flagged_invoices),
        false_positive_examples=sorted(found - expected, key=str)[:20],
        false_negative_examples=sorted(expected - found, key=str)[:20],
    )


def evaluate_tables(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    labels: Sequence[Mapping[str, Any]],
    config: MatchConfig | None = None,
) -> tuple[MatchOutcome, EvaluationReport]:
    outcome = run_matching(Snapshot.from_rows(tables), config)
    return outcome, evaluate(outcome, labels)


def sweep_duplicate_threshold(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    labels: Sequence[Mapping[str, Any]],
    thresholds: Sequence[Decimal],
) -> list[tuple[Decimal, CodeMetrics]]:
    """Duplicate precision/recall per threshold (used for tuning on a separate seed)."""
    snapshot = Snapshot.from_rows(tables)
    results = []
    for th in thresholds:
        cfg = MatchConfig(duplicates=DuplicateConfig(threshold=th))
        report = evaluate(run_matching(snapshot, cfg), labels)
        results.append((th, report.metrics("DUPLICATE_SUSPECTED")))
    return results


def label_counts(labels: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for lb in labels:
        counts[lb["label_code"]] += 1
    return dict(counts)


def render_markdown(title: str, report: EvaluationReport, context: Mapping[str, str]) -> str:
    lines = [f"# {title}", ""]
    lines += [f"- **{k}:** {v}" for k, v in context.items()]
    lines += [
        "",
        "## Targets (decision D3)",
        "",
        "| Metric | Value | Target | Result |",
        "|---|---|---|---|",
    ]
    for name, (value, target, ok) in report.target_checks().items():
        op = "<=" if name.endswith("fp_rate") else ">="
        lines.append(f"| {name} | {value:.3f} | {op} {target} | {'PASS' if ok else 'MISS'} |")
    lines += [
        "",
        "## Per exception code",
        "",
        "| Code | TP | FP | FN | Precision | Recall |",
        "|---|---|---|---|---|---|",
    ]
    for m in report.per_code:
        lines.append(
            f"| {m.code} | {m.tp} | {m.fp} | {m.fn} | {m.precision:.3f} | {m.recall:.3f} |"
        )
    lines += [
        "",
        "## Hard negatives (legitimate look-alikes)",
        "",
        f"{report.hard_negative_false_positives} of {report.hard_negative_invoices} "
        f"look-alike invoices received an exception "
        f"(false-positive rate {report.hard_negative_fp_rate:.2%}).",
        "",
    ]
    if report.false_negative_examples or report.false_positive_examples:
        lines += [
            "## Examples",
            "",
            f"- Missed: {report.false_negative_examples[:10]}",
            f"- False alarms: {report.false_positive_examples[:10]}",
            "",
        ]
    return "\n".join(lines)
