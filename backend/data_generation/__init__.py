"""Seeded synthetic ERP data generator for EnterpriseOps AI.

Produces an SAP-aligned procure-to-pay dataset for a fictional pump manufacturer,
with deliberately injected, labeled exceptions (ground truth for evaluation).

Usage (from backend/):
    uv run python -m data_generation generate --seed 42 --profile full
    uv run python -m data_generation validate
"""

GENERATOR_VERSION = "1.1.0"
