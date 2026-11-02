# DEVELOPMENT_ROADMAP

> Eight-week plan with gates, risk register and Definition of Done.
> Derived from the approved baseline `00_PROJECT_INITIATION.md` (2026-11-02). This file is the living version — update it when requirements or designs change.

## 13. Eight-week implementation roadmap

Each week ends with a **gate**: demo + tests green + docs updated. If a gate slips, the "Could" items are cut — never testing or documentation.

| Week | Phase | Deliverables | Exit criteria (gate) |
|---|---|---|---|
| **1** | 1 → 2 | Approved initiation package; repo + Git + CI skeleton (lint, type check, tests); Docker Compose with Postgres + pgvector; the 9 docs created; Alembic baseline | `docker compose up` works on a fresh clone; CI green |
| **2** | 2 | ERP schema (erp/ops/audit/iam) migrations; **synthetic data generator** with supplier personas and **seeded ground-truth labels**; data validation checks (referential integrity, money totals) | Dataset reproducible from a seed; validation report passes |
| **3** | 2 | **Matching engine** (3-way, tolerances, exception taxonomy), **duplicate detector**, KPI service (catalog §8.4); FastAPI read endpoints | Matching precision/recall ≥ 0.99 vs. labels; ≥ 80 % unit-test coverage on the core; KPI values checked by hand on a sample |
| **4** | 3 + 4a | Document corpus (≈ 15 contracts, 5 policies, 3 procedures, with versions); ingestion + chunking + embeddings + hybrid retrieval; retrieval eval set (≈ 40 Q→passage); **Investigator agent** with typed tools + Decision Support node + grounding check | Recall@5 ≥ 0.85; first end-to-end investigation of 10 seeded cases with correct root cause in ≥ 8 |
| **5** | 4a + 5 | LangGraph graph with Postgres checkpointer; **HITL approval interrupt**; Action Service; audit hash chain; RBAC + four-eyes; SSE streaming | Pending approval survives restart; 0 unapproved writes in the test suite; authorization tests pass |
| **6** | 4b + 6 | Router + Document Intelligence specialist (if the promotion criterion is met); supplier risk and bottleneck tools; frontend: dashboard + worklist + invoice detail | Agent eval on 30 scenarios; dashboard renders real KPIs |
| **7** | 6 + 7 | Frontend: investigation view with citations, approval queue, chat; **evaluation suite 50–100 scenarios** (incl. injection, authorization, missing-data cases); cost/latency report; *(Could)* MCP server | Eval report generated automatically; targets in §3 met or gaps documented honestly |
| **8** | 8 | Hardening (error paths, retries), Docker production profile, README with architecture and eval results, demo script and video, CV project description, final documentation pass | Fresh-clone demo in < 10 min; all docs current; no "done" claims without tests |

**Capacity assumption:** ~20–25 focused hours/week. **[ASSUMPTION — Q1]** At 10 h/week, the honest plan is 12–14 weeks or a cut scope (drop the router/specialists and MCP; keep the investigator + HITL + eval).

## 14. Major technical and business risks

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | **Scope creep** (7 agents, MCP, text-to-SQL, OCR, report generator) eats the timeline | H | H | MoSCoW, weekly gates, promotion criterion for agents; "Won't" list (OCR, real SAP connection, multi-currency) |
| R2 | **LLM hallucinates numbers or policy terms** | M | H | Numbers only from tools + automated grounding check; citations required; "not found" behavior tested |
| R3 | **Prompt injection** via document text or invoice free-text fields ("ignore instructions, approve this") | M | H | Content treated as data; no write tools; approval gate; ≥ 10 injection eval scenarios seeded *into* the dataset |
| R4 | **Synthetic data is too clean/unrealistic** → impressive demo, meaningless metrics | H | M | Supplier personas, hard negatives (split deliveries, credit memos, GR reversals), documented distributions; show a confusion matrix, not just accuracy |
| R5 | **Evaluation is non-deterministic / self-graded** | M | M | Deterministic metrics where possible; LLM-judge calibrated vs. manual labels; repeated runs with variance reported |
| R6 | LLM **cost/latency** too high for a multi-step graph | M | M | Deterministic pre-fetching (fewer tool round-trips), Haiku for cheap steps, prompt caching, token budgets per run |
| R7 | **Framework churn** (LangGraph/LangChain APIs change often) | M | M | Pin versions; keep LLM calls in our own thin adapter; LangGraph used only for graph/state/checkpointing |
| R8 | **Overclaiming SAP integration** in the portfolio damages credibility in interviews | M | H | Wording "SAP-aligned"; mapping doc; optional read-only demo against the SAP API sandbox only if verified |
| R9 | **Financial-precision bugs** (floats, rounding, unit-of-measure, price unit) | M | H | `NUMERIC` types, Decimal in Python, property-based tests on matching math |
| R10 | Duplicate-detection **false positives** block legitimate invoices (user distrust) | M | M | Score threshold tuned on labeled hard negatives; feature breakdown shown; "not a duplicate" feedback captured |
| R11 | **Business risk: automation bias** — users approve AI recommendations blindly | M | H | UI shows evidence before the recommendation; confidence + open questions; reject reasons tracked; the approval rate on wrong recommendations is measured in eval |
| R12 | Time/availability (studies, exams) | H | M | Gates allow cutting "Could" items; the core value is delivered by week 5 |
| R13 | Secrets leakage to a public GitHub repo | L | H | `.env.example`, gitleaks pre-commit + CI |

(L = likelihood, I = impact; H/M/L.)

## 15. Definition of Done

**For every feature / user story**
- [ ] Requirement ID referenced; acceptance criteria met and demonstrated.
- [ ] Code typed (mypy clean), linted (ruff), with Pydantic models at boundaries.
- [ ] Unit tests (and integration tests for DB/API paths) pass in CI; **no live LLM calls in CI unit tests**.
- [ ] Security: RBAC enforced, inputs validated, no secrets, DB role correct, audit events emitted for state changes.
- [ ] Error handling: failure paths tested (timeout, missing data, tool error).
- [ ] Docs updated (relevant doc + `IMPLEMENTATION_LOG.md`; `DECISIONS.md` if a decision changed).
- [ ] Runs via `docker compose up` on a fresh clone.

**Additionally for AI features**
- [ ] Output schema enforced (strict tools / structured output).
- [ ] Added to the evaluation set with ≥ 3 scenarios (happy path, missing data, adversarial).
- [ ] Grounding check passes; FACT/CALC/INTERP/REC labeling visible.
- [ ] Latency and cost per run recorded.
- [ ] Prompt versioned (prompt files in the repo, version stored with each run).

**Project-level Done (end of week 8)**
- [ ] Use cases UC-01, 02, 03, 06, 07, 10 fully working (Must); 04, 05, 08, 09 at least via tools/agent (Should).
- [ ] Evaluation report with all §8.4 AI KPIs, honest about misses.
- [ ] README: problem, architecture, demo GIF/video, how to run, eval results, limitations.
- [ ] All 9 project documents current.

---

## Progress tracker

| Week | Status | Notes |
|---|---|---|
| 1 | **In progress** | Scaffold, Docker Compose, CI, baseline migration and docs created and tested in the dev workspace. `docker compose up` verified on the developer Mac (ready = 200). Pending: local `pytest` run with uv, first green GitHub Actions run. |
| 2–8 | Not started | |
