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

## 3. Current test inventory (Task 1)

| Test | Verifies | Type |
|---|---|---|
| `test_liveness_returns_ok` | `/health/live` contract | Unit |
| `test_response_carries_generated_request_id` | Request ID generated | Unit |
| `test_valid_incoming_request_id_is_propagated` | Caller's request ID is kept | Unit |
| `test_malicious_request_id_is_replaced` | Log-injection defense on the header | Unit (security) |
| `test_readiness_is_503_when_database_unreachable` | Failure path returns 503 | Unit (failure) |
| `test_openapi_schema_is_published` | API docs are generated | Unit |
| `test_readiness_is_ready_after_migrations` | Readiness against the real DB | Integration |
| `test_baseline_creates_domain_schemas` | Migration creates the 5 schemas | Integration |
| `test_baseline_installs_pgvector` | The vector extension exists | Integration |
| `test_downgrade_and_reupgrade_round_trip` | The migration is reversible | Integration |

**Last verified run** (2026-11-02, dev workspace: Python 3.12.3, PostgreSQL 16 + pgvector 0.6.0):
10 passed; coverage 95 %; ruff, ruff format and mypy (strict) clean.
Docker stack verified on the developer Mac (PostgreSQL 17.11 + pgvector, readiness 200). Developer Mac: 10 passed, 95 %. GitHub Actions run #41474098669: all jobs green, integration tests executed (`EOPS_REQUIRE_DB=1`).

## 4. AI evaluation plan (Tasks 4–7)

The KPI definitions are in `PROJECT_REQUIREMENTS.md` §8.4 (AI/system KPIs). Planned datasets in `evaluation/`:

| Dataset | Size | Measures |
|---|---|---|
| Seeded ERP labels (`ground_truth_label`) | all invoices | Matching and duplicate precision/recall, confusion matrix |
| Retrieval set (question → expected passage IDs) | ~40 | Recall@5, MRR |
| Agent scenarios | 50–100 | Task success (rubric), tool-selection accuracy, grounded-number rate, citation accuracy, latency, cost |
| Adversarial set | ≥ 10 injection + ≥ 10 authorization | Injection resistance, unsafe-action rate (must be 0) |

Reporting rules: report variance over repeated runs for LLM metrics; calibrate any LLM-as-judge against a manually labeled sample; document misses honestly.
