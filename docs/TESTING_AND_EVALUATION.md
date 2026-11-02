# TESTING_AND_EVALUATION

> Test strategy, how to run the tests, current results, and the evaluation plan for the AI components.

## 1. Test levels

| Level | Scope | Needs DB | Needs LLM | Runs in CI |
|---|---|---|---|---|
| Unit | Pure functions, API behavior with dependencies overridden | No | **Never** | Yes |
| Integration (`@pytest.mark.integration`) | Migrations, SQL, services against real PostgreSQL + pgvector | `eops_test` | No | Yes (required) |
| Agent tests (Task 4+) | Graph logic with **recorded/mocked** LLM responses | `eops_test` | No | Yes |
| Live evaluation (Task 4+) | Real Claude calls on the scenario dataset; produces the eval report | `eops_test` | Yes | Manual / scheduled, not on every push |

**Rules**
- Tests use the separate `eops_test` database (`EOPS_TEST_DATABASE_URL`), never development data.
- `EOPS_TEST_DATABASE_URL` is read from the shell or, if not set there, from the repo-root `.env` (loaded by `tests/conftest.py`). Without it, integration tests are **skipped**.
- With `EOPS_REQUIRE_DB=1` (always set in CI), a missing database is an **error**, so CI can never pass by silently skipping integration tests.
- Coverage gate in CI: **≥ 80 %** overall; the target for the deterministic core (matching, duplicates, KPIs) is ≥ 90 %.

## 2. How to run

```bash
cd backend
uv run pytest                          # unit tests; integration tests skipped
uv run pytest -m integration           # only integration tests (needs EOPS_TEST_DATABASE_URL)
uv run pytest --cov --cov-report=term-missing
uv run ruff check . && uv run ruff format --check . && uv run mypy   # same gates as CI
```

## 3. Current test inventory (after Task 2)

| File | Tests | Verifies | Type |
|---|---|---|---|
| `test_health.py` | 11 | Liveness/readiness contract, request-ID handling (incl. log-injection defense), 503 on DB failure, readiness reports the head migration, health probes logged at DEBUG, OpenAPI published | Unit + 1 integration |
| `test_migrations.py` | 4 | Schemas and all 21 tables exist, pgvector installed, full downgrade/upgrade round trip | Integration |
| `test_schema_drift.py` | 1 | Migrated DB == `app/db/tables.py` (ADR-017) | Integration |
| `test_db_roles.py` | 8 | Agent role reads erp/ops; INSERT/UPDATE/DELETE on erp and any read of eval/iam denied; app role can't write erp; action role can | Integration (security) |
| `test_data_generation.py` | 10 | Same seed → identical content hash; different seed differs; all 17 label codes present; labels reference real rows; invoice totals; chronological IDs; full-profile exception rate 15–25 %; catalog guard; loader refuses production | Unit |
| `test_dataset_integration.py` | 3 | Small dataset loads and passes all 19 validation checks; reload is idempotent (reference roles survive); CLI generate + validate exit 0 | Integration |

**Last verified run** (2026-11-02, dev workspace: Python 3.12.3, PostgreSQL 16 + pgvector 0.6.0):
**37 passed**; coverage 99 % (`app` + `data_generation`); ruff, ruff format, mypy (strict, 26 files) clean.
Developer Mac and GitHub Actions: pending for Task 2 (Task 1 state: all green).

## 4. AI evaluation plan (Tasks 4–7)

The KPI definitions are in `PROJECT_REQUIREMENTS.md` §8.4 (AI/system KPIs). Planned datasets in `evaluation/`:

| Dataset | Size | Measures |
|---|---|---|
| Seeded ERP labels (`ground_truth_label`) | all invoices | Matching and duplicate precision/recall, confusion matrix |
| Retrieval set (question → expected passage IDs) | ~40 | Recall@5, MRR |
| Agent scenarios | 50–100 | Task success (rubric), tool-selection accuracy, grounded-number rate, citation accuracy, latency, cost |
| Adversarial set | ≥ 10 injection + ≥ 10 authorization | Injection resistance, unsafe-action rate (must be 0) |

Reporting rules: report variance over repeated runs for LLM metrics; calibrate any LLM-as-judge against a manually labeled sample; document misses honestly.

## 5. Synthetic ERP dataset (Task 2)

### 5.1 What is generated
A fictional pump manufacturer (Talwerk Pumpen GmbH, DE01/EUR, plus Talwerk Pumps Inc., US01/USD) over
18 months (2025-04-01 to 2026-09-30). Process: PO → shipment(s) → goods receipt(s) → one invoice per
shipment → payment. Everything is generated **clean**, then scenarios inject exceptions.

**Supplier personas** (hidden in `eval.supplier_persona`): reliable (~60 %), chronically late (15 %),
price creep (10 %), sloppy invoicer (15 %), one fraud signal, plus one duplicate vendor master record
(same VAT ID as a sloppy supplier). Observed in seed 42: late suppliers average 8.3 days delay
(39 % on time) vs 0.4 days (88 %) for reliable ones; price-creep suppliers have a 42 % exception rate.

### 5.2 Scenarios and labels (seed 42, full profile: invoices per label)
| Code | Invoices | How it is created | Engine must flag? |
|---|---|---|---|
| PRICE_VARIANCE | 212 | +4–15 % on one line (random) or +3–10 % creeping after month 6 (price-creep persona) | Yes |
| QTY_VARIANCE | 101 | Short delivery (80–95 %) but full quantity invoiced | Yes |
| NO_GOODS_RECEIPT | 68 | Receipt never posted, or posted and fully reversed (102) | Yes |
| PO_OVER_INVOICED | 17 | Over-delivery accepted and invoiced above PO quantity | Yes |
| NO_PO_REFERENCE | 68 | Service invoices without PO | Yes |
| CONTRACT_PRICE_DEVIATION | 51 | PO price 3–8 % above contract; invoice matches PO | Yes (flag only) |
| PAYMENT_TERMS_MISMATCH | 68 | Invoice states different terms than PO | Yes (flag only) |
| CURRENCY_MISMATCH | 17 | EUR PO invoiced in USD | Yes |
| DUPLICATE_SUSPECTED | 52 | Same invoice again: exact / reformatted reference / other vendor master | Yes |
| BANK_DETAILS_CHANGED | 7 | Fraud-signal supplier changes bank 3–12 days before invoices | Yes |
| HN_PARTIAL_DELIVERY | 889 | Two shipments, two invoices — quantities match | **No** |
| HN_PRICE_WITHIN_TOLERANCE | 34 | +0.4–1.5 %, ≤ 49.45 | **No** |
| HN_SMALL_DIFFERENCE | 27 | > 2 % but ≤ 4.45 absolute (BD rule) | **No** |
| HN_GR_REVERSAL_REPOSTED | 17 | 101 → 102 → 101 again; net quantity correct | **No** |
| HN_CREDIT_MEMO_SAME_REF | 55 | Credit memo reuses the invoice's reference | **No** |
| HN_SAME_AMOUNT_DIFFERENT_PO | 29 | Repeat order: same amount, different PO and reference | **No** |
| HN_OLD_BANK_CHANGE | 3 | Bank change ≥ 40 days before any invoice | **No** |

**Exception rate:** 661 of 3,496 invoices (18.9 %) carry at least one real exception (target band 15–25 %).

### 5.3 Validation report (19 checks)
`uv run python -m data_generation validate` — groups: *integrity* (11: totals, tax, dates, reversals,
payments, bank-account history), *clean-data* (5: unlabeled invoices really match PO price, currency,
terms, contract price, received quantity; no unlabeled duplicate references) and *coverage* (3: label
references, every scenario present, exception rate in band).

**Robustness:** all 19 checks pass for full-profile seeds 1, 7, 42, 123, 2026, 99999 and small-profile
seeds 1–12. (Small seed 2 initially lacked HN_SMALL_DIFFERENCE; the candidate range was widened and the
markup capped so the difference stays ≤ 4.50 — see IMPLEMENTATION_LOG.)

### 5.4 Ground-truth usage (Task 3 onwards)
Matching precision/recall = engine exceptions vs labels with `is_hard_negative = false`, per code;
false-positive rate on hard negatives is reported separately. Labels are only readable by the
evaluation harness (ADR-018).
