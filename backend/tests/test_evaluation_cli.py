"""Evaluation command line in memory (no database)."""

from pathlib import Path

import pytest

from evaluation.__main__ import main


def test_matching_command_writes_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = tmp_path / "report.md"
    assert main(["matching", "--seed", "42", "--profile", "small", "--report", str(report)]) == 0
    text = report.read_text()
    assert "| rule_precision |" in text and "MISS" not in text
    assert "[PASS] duplicate_recall" in capsys.readouterr().out


def test_tune_duplicates_prints_sweep(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tune-duplicates", "--seed", "7"]) == 0
    out = capsys.readouterr().out
    assert "0.60" in out and "P=" in out
