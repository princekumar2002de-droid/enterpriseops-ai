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

## 3. Current test inventory (after Task 3)

| File | Tests | Verifies | Type |
|---|---|---|---|
| `test_health.py` | 11 | Liveness/readiness, request IDs (incl. log-injection defense), 503 path, head migration, probe logging | Unit + 1 integration |
| `test_migrations.py` | 4 | 7 schemas, 26 base tables, pgvector, full downgrade/upgrade round trip | Integration |
| `test_schema_drift.py` | 1 | Migrated DB == `app/db/tables.py` | Integration |
| `test_db_roles.py` | 21 | Agent role: all 9 views readable; erp/ops tables, bank accounts, iam, eval denied; app role only `payment_block`; action role writes erp; no IBAN in views | Integration (security) |
| `test_data_generation.py` | 10 | Generator determinism, scenario coverage, totals, exception-rate band, guards | Unit |
| `test_dataset_integration.py` | 3 | Load + 19 validation checks, idempotent reload, generator CLI | Integration |
| `test_matching_rules.py` | 22 | Price rules incl. BD / %-OR-absolute / lower side / exact limits, quantity rules, over-invoicing, contract, bank window, reference normalisation, duplicate scores | Unit |
| `test_matching_engine.py` | 11 | Precedence R1–R5, flag-only codes, params hash stability, **Task 3 targets on seeds 42 full/small and 3 small (CI gate)** | Unit |
| `test_matching_db.py` | 5 | DB run == in-memory run, payment block only on unpaid blocked invoices, versioned runs, agent views show latest run, run + `evaluation db` CLIs | Integration |
| `test_api_v1.py` | 15 | Paging/filters, three-way evidence in invoice detail, duplicate links, sort order, 7 error-envelope cases, all KPIs compute, **2 KPIs equal an independent Python calculation**, supplier breakdown | Integration |
| `test_evaluation_cli.py` | 2 | Evaluation report written, tuning sweep | Unit |

**Last verified run** (2026-11-02, dev workspace, PostgreSQL 16): **105 passed**, coverage 98 % overall,
**100 % on the matching core** (engine, rules, duplicates, snapshot); ruff, format and mypy strict (50 files) clean.
Developer Mac and GitHub Actions for Task 3: pending.

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
(same VAT ID as a sloppy supplier). Observed in seed 42: late suppliers average 8.5 days delay
(39 % on time) vs 0.4 days (88 %) for reliable ones; price-creep suppliers have a 41.3 % exception rate
(reliable: 13.3 %).

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

**Dataset fingerprint (seed 42, full):** generator 1.1.0 → content hash `32a2a5b2249fe8dd…`, 35,606 rows (generator 1.0.0 was `477673a2b9fa2927…`; 1.1.0 only changed payment dates, labels are identical).
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

## 6. Matching engine evaluation (Task 3)

Command: `uv run python -m evaluation matching --seed 42 --report evaluation/reports/matching_seed42_full.md`
(in memory) or `uv run python -m evaluation db` (latest DB run vs. the labels in `eval`).

### 6.1 Results — reporting seed 42 (full profile, engine 1.0.0, generator 1.1.0)
| Code | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| BANK_DETAILS_CHANGED | 7 | 0 | 0 | 1.000 | 1.000 |
| CONTRACT_PRICE_DEVIATION | 51 | 0 | 0 | 1.000 | 1.000 |
| CURRENCY_MISMATCH | 17 | 0 | 0 | 1.000 | 1.000 |
| DUPLICATE_SUSPECTED | 52 | 0 | 0 | 1.000 | 1.000 |
| NO_GOODS_RECEIPT | 148 | 0 | 0 | 1.000 | 1.000 |
| NO_PO_REFERENCE | 102 | 0 | 0 | 1.000 | 1.000 |
| PAYMENT_TERMS_MISMATCH | 68 | 0 | 0 | 1.000 | 1.000 |
| PO_OVER_INVOICED | 17 | 0 | 0 | 1.000 | 1.000 |
| PRICE_VARIANCE | 385 | 0 | 0 | 1.000 | 1.000 |
| QTY_VARIANCE | 101 | 0 | 0 | 1.000 | 1.000 |

Look-alike (hard-negative) invoices flagged: **0 of 1,051** (0.00 %). All five D3 targets pass.
Identical results on full seeds 1, 7, 123, 2026 and small seeds 1–5.

### 6.2 How to read these numbers (honest interpretation)
- **Rule-based codes at 100 %** mainly prove that the engine implements the written rules (§8.2)
  correctly: labels and engine follow the same rules. They do **not** prove the rules are the right
  business rules — that is a domain decision, documented in §8.2 and the AP Tolerance Policy (Task 4).
- **The informative results** are the hard negatives (0 / 1,051 false alarms on partial deliveries,
  in-tolerance prices, small differences, reposted receipts, credit memos, repeat orders, old bank
  changes) and the duplicate detector.
- **Duplicate threshold sweep on the tuning seed 7** (decision D2):

  | Threshold | TP | FP | FN | Precision | Recall |
  |---|---|---|---|---|---|
  | 0.30 | 52 | 41 | 0 | 0.559 | 1.000 |
  | 0.35–0.45 | 52 | 13 | 0 | 0.800 | 1.000 |
  | 0.50–1.00 | 52 | 0 | 0 | 1.000 | 1.000 |

  Chosen: **0.60** (largest margin above the false-positive cliff). Limitation: every synthetic duplicate
  scores 1.00, so the data cannot discriminate between thresholds in 0.50–1.00. Backlog: harder
  duplicate variants (re-issued with a new number, amended amount) to make this trade-off measurable.

### 6.3 Business view of the run (seed 42, DE01 unless noted)
| KPI | Value | n |
|---|---|---|
| First-pass match rate | 80.74 % | 3,177 invoices |
| Exception rate | 19.26 % | 3,177 |
| Blocked open invoices (DE01 / all) | 81 / 87 | — |
| Supplier OTIF | 61.48 % | 5,873 PO items |
| Average delivery delay | 1.95 days | 5,873 |
| Price variance | 0.535 % of invoiced value | 6,922 lines |
| Non-PO invoice share | 2.14 % | 3,177 |
| Cash-discount capture | 41.88 % | 1,181 |
| Late payment rate | 12.84 % | 2,936 |
| Receipt-to-payment (median) | 25 days | 2,936 |
| PO-to-receipt lead time (median) | 24 days | 5,873 |

The KPI layer surfaced a data-realism bug (late payment rate was 35.9 %): see IMPLEMENTATION_LOG, Task 3.
