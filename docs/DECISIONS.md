# DECISIONS.md — Architecture Decision Records

Format: Context → Decision → Consequences. Status values: **Proposed** · Accepted · Superseded · Rejected.
ADR-001 to ADR-012 were proposed in Phase 1 and **approved on 2026-11-02**. Later ADRs are added as decisions are made.

---

## ADR-001 — Deterministic matching core; the LLM explains only
**Status:** Accepted (2026-11-02)
**Context:** Three-way matching, tolerance checks and duplicate detection are financial controls. They must be exact, reproducible and auditable. LLM outputs are probabilistic.
**Decision:** Implement matching, duplicate scoring and KPIs as tested Python/SQL services. Agents consume their results via tools and explain them.
**Consequences:** + measurable precision/recall, unit-testable, cheap. − Rules must be maintained explicitly (which is also what real ERP systems do).

## ADR-002 — Start with one investigation agent; add specialists on evidence
**Status:** Accepted (2026-11-02)
**Context:** The brief proposes 7 agents. More agents add latency, cost, failure points and evaluation complexity. LangChain's multi-agent guidance notes that a single agent with good tools often suffices; splitting helps when the tool set or prompts become too large.
**Decision:** Phase 4a = Investigator agent + Decision Support synthesis node + deterministic nodes. Phase 4b = LLM router + Document Intelligence specialist. Supplier Intelligence and Business Process start as tool groups. **Promotion criterion:** split a tool group into its own agent if tool-selection accuracy < 90 % or task success drops > 5 pp on the eval set.
**Consequences:** + working value earlier, measurable justification for each agent. − Fewer named agents in early demos.

## ADR-003 — Agents have no write tools
**Status:** Accepted (2026-11-02)
**Context:** Sensitive writes (releasing payment blocks, credit memos) must never happen without human approval. Prompt injection via documents or invoice texts is a realistic threat.
**Decision:** Agents can only call `propose_action`. A LangGraph `interrupt()` pauses for approval; a deterministic Action Service executes approved actions with idempotency keys, RBAC, four-eyes and audit. Side effects are kept out of the interrupting node, because the node re-executes from its start on resume.
**Consequences:** + structurally safe. − Slightly more plumbing.

## ADR-004 — Typed tool catalog instead of free text-to-SQL
**Status:** Accepted (2026-11-02)
**Context:** The brief forbids arbitrary SQL by the LLM but also wants SQL analysis.
**Decision:** Parameterized, allow-listed tools with enums (KPI names, exception codes, dimensions). Optional later feature: constrained text-to-SQL over curated read-only views with AST validation (SELECT only, view allow-list, enforced LIMIT, statement_timeout, read-only role).
**Consequences:** + secure and testable. − Questions outside the catalog need new tools (or the optional feature).

## ADR-005 — LangGraph for orchestration; official Anthropic SDK in nodes
**Status:** Accepted (2026-11-02)
**Context:** We need durable state, checkpointing and human-in-the-loop pauses. We also want direct control over Claude features (strict tool use, prompt caching).
**Decision:** LangGraph (`StateGraph`, Postgres checkpointer, `interrupt`/`Command(resume=...)`). LLM calls go through a thin internal adapter over the `anthropic` SDK. Versions are pinned.
**Consequences:** + durable HITL without building it ourselves; no wrapper lag. − Some LangSmith auto-instrumentation must be added manually (SDK wrapper).

## ADR-006 — PostgreSQL as the single data platform
**Status:** Accepted (2026-11-02)
**Context:** Relational ERP data, vectors, full-text search, checkpoints and audit are all needed; the scale is small (<100k chunks).
**Decision:** PostgreSQL 17 + pgvector (HNSW, iterative index scans) + FTS; hybrid retrieval merged with Reciprocal Rank Fusion. Separate schemas and DB roles per concern.
**Consequences:** + one system, transactional consistency, simpler ops. − Not a showcase of a dedicated vector DB (deliberately).

## ADR-007 — SAP-aligned, not SAP-integrated
**Status:** Accepted (2026-11-02)
**Context:** No live SAP system access is assumed. Claiming integration would be inaccurate.
**Decision:** The data model mirrors S/4HANA objects (EKKO/EKPO, MATDOC, RBKP/RSEG, LFA1/BP). An `ErpAdapter` interface has a simulated implementation; a mapping to S/4HANA OData APIs is documented (names to be verified on api.sap.com).
**Consequences:** + credible and honest; clear extension path. − No live integration demo in v1.

## ADR-008 — Synthetic data with seeded ground-truth labels
**Status:** Accepted (2026-11-02)
**Decision:** A reproducible generator (fixed seed) with supplier personas, realistic exception rates, hard negatives and a hidden label table used only by evaluation.
**Consequences:** + quantitative evaluation of matching and agents.

## ADR-009 — MCP as an outer interface only
**Status:** Accepted (2026-11-02)
**Decision:** Internal tool calls stay in-process. Optionally (Task 7), expose the read-only tool registry as an MCP server for external MCP clients.
**Consequences:** + demonstrates MCP without adding latency or complexity to the core path.

## ADR-010 — Pandas offline only; aggregation in SQL
**Status:** Accepted (2026-11-02)
**Decision:** Pandas/NumPy are used for data generation and offline reports. API/agent paths use SQL aggregation.
**Consequences:** + fast request path; single source of KPI logic.

## ADR-011 — No Celery/Redis in v1
**Status:** Accepted (2026-11-02)
**Decision:** FastAPI + LangGraph durable runs are sufficient for second-scale investigations. Revisit if batch workloads appear.

## ADR-012 — Money as NUMERIC/Decimal
**Status:** Accepted (2026-11-02)
**Decision:** `NUMERIC(15,2)` for amounts and `NUMERIC(15,4)` for unit prices; Python `Decimal`; no floats in matching math.

---

## ADR-013 — uv for Python dependency management
**Status:** Accepted (2026-11-02)
**Context:** We need reproducible installs on the developer Mac, in Docker and in CI.
**Decision:** Use `uv` with `pyproject.toml` + a committed `uv.lock`; CI and Docker install with `uv sync --frozen`. Dev tools (pytest, ruff, mypy) live in a `dev` dependency group, excluded from the image.
**Consequences:** + exact same versions everywhere, fast installs. − One extra tool to install (`brew install uv`). Alternative rejected: pip + requirements.txt (no lockfile with hashes for transitive dependencies unless pip-tools is added).

## ADR-014 — Migrations run as a one-shot compose job, not at API startup
**Status:** Accepted (2026-11-02)
**Context:** Running `alembic upgrade` inside the API start command races when several API replicas start, and it hides migration failures inside API logs.
**Decision:** A separate `migrate` service runs `alembic upgrade head` and exits; `api` starts only after it completed successfully.
**Consequences:** + clear failure point, mirrors a production "release job". − One more service in the compose file.

## ADR-015 — Separate test database; CI must not skip integration tests
**Status:** Accepted (2026-11-02)
**Decision:** Integration tests run only against `EOPS_TEST_DATABASE_URL` (`eops_test`). Locally they skip if it is unset. In CI, `EOPS_REQUIRE_DB=1` turns a missing DB into a failure.
**Consequences:** + tests can drop/recreate schemas safely; CI can't go falsely green.

## ADR-016 — Tolerance rule: flag when either limit is breached
**Status:** Accepted (2026-11-02)
**Context:** Tolerance rules have a percentage and an absolute (EUR) limit. They can be combined with OR (strict) or AND (lenient).
**Decision:** A variance is out of tolerance if it exceeds the percentage limit **or** the absolute limit (lower and upper bounds evaluated separately). The AP Tolerance Policy document must state exactly this rule so the deterministic engine and the RAG corpus never contradict each other.
**Consequences:** + conservative financial control; small-value lines with a high percentage variance are caught. − More exceptions on low-value lines, handled by the small-difference (BD-like) auto-accept limit.

## ADR-017 — Table definitions in code; reviewed autogenerated migrations; drift test
**Status:** Accepted (2026-11-02)
**Context:** 21 tables now and more later. Hand-writing both models and migrations invites silent divergence.
**Decision:** `app/db/tables.py` (SQLAlchemy Core, fixed constraint naming convention) is the single source of truth. Migrations are produced by `alembic revision --autogenerate`, reviewed and committed; hand-written parts (schemas, grants, reference data) are marked `MANUAL`. `tests/test_schema_drift.py` compares the migrated database with `tables.py` and must report no differences.
**Consequences:** + one definition, typed Python access for services, guaranteed consistency. − Reviewers must still read each generated migration (autogenerate misses e.g. grants and data).
**Alternative rejected:** ORM models (not needed: services will use SQL / Core queries); raw-SQL-only migrations (no typed table objects, drift undetectable).

## ADR-018 — Ground truth in a separate `eval` schema
**Status:** Accepted (2026-11-02)
**Context:** The generator knows which invoices are exceptions. If the agent could read those labels, evaluation would be meaningless (and a prompt-injected agent could "cheat").
**Decision:** Labels, supplier personas and dataset provenance live in schema `eval`. No application or agent role has any privilege on it; only the evaluation harness (owner role) reads it.
**Consequences:** + evaluation integrity enforced by the database, not by convention.

## ADR-019 — Generator: stdlib `random` + Faker, inside the backend project
**Status:** Accepted (2026-11-02)
**Context:** The approved stack lists Pandas/NumPy, but generation only needs seeded sampling (uniform, choices, weighted picks).
**Decision:** Python's `random.Random(seed)` drives all randomness; **Faker** (new dev dependency) supplies realistic company names, cities and IBANs. NumPy/Pandas are not added until a feature needs them (e.g. KPI reports). The generator lives in `backend/data_generation/` so it shares the uv environment and `tables.py`; Faker sits in the `dev` group, so it is not in the API image.
**Consequences:** + fewer dependencies, fully reproducible (seed + lockfile → identical content hash). − Generating data requires the dev environment (`uv sync`).

## ADR-020 — Database group roles and least privilege
**Status:** Accepted (2026-11-02)
**Decision:** Migration 0002 creates `NOLOGIN` group roles `eops_agent_ro` (read erp/ops), `eops_app` (read erp/iam, write ops) and `eops_action` (the only role that writes erp; no DELETE). Grants are applied per migration. Roles are cluster-wide, so downgrades revoke privileges but never drop roles. In Task 3, `eops_agent_ro` is narrowed to curated views.
**Consequences:** + "agents cannot write ERP data" is enforced by PostgreSQL and tested. − Each new migration must re-apply grants for its tables.

## ADR-021 — Labeling semantics for synthetic exceptions
**Status:** Accepted (2026-11-02)
**Decision:** (1) Data is generated clean first; each scenario changes exactly one invoice (at most one scenario per invoice), so every label has one cause. (2) Labels state what a correct engine must report under the rules T1–T3 / R1–R5 in PROJECT_REQUIREMENTS §8.2. (3) Hard negatives (`HN_*`, `is_hard_negative = true`) are legitimate look-alikes (partial deliveries, credit memos with the same reference, reversed-and-reposted receipts, repeat orders, in-tolerance and small-difference prices, old bank changes) used to measure false positives. (4) A validation report checks that unlabeled data really is clean.
**Consequences:** + precision/recall/false-positive rate are measurable; generator bugs can't silently become false ground truth. − Single-cause invoices are cleaner than reality; multi-exception invoices can be added later as a separate, explicitly labeled scenario.

## ADR-022 — Agents read curated `agent` views only
**Status:** Accepted (2026-11-02)
**Context:** ADR-020 gave the agent role SELECT on whole erp/ops tables as an interim step.
**Decision:** Migration 0003 creates schema `agent` with 9 read-only views (invoice overview, line match, goods receipts, purchase orders, contract prices, supplier profile, open exceptions, duplicate pairs, latest run). `eops_agent_ro` loses all access to erp/ops tables and can read only these views. Views expose no bank details (only `last_bank_change_date`), no ground truth and no user data. The API reads the same views, so "latest completed run" has a single definition.
**Consequences:** + the agent's data surface is explicit, reviewable and tested. − New agent data needs a new/changed view (a migration).

## ADR-023 — Matching engine is a pure function over a snapshot; runs are versioned
**Status:** Accepted (2026-11-02)
**Decision:** `run_matching(Snapshot, MatchConfig) -> MatchOutcome` has no I/O. A snapshot is built from DB rows or from generated rows with the same column names, so the engine is unit-testable and the evaluation harness can score any seed in memory. Each persisted run stores engine version, full parameters and a SHA-256 params hash; runs are appended, never overwritten. Concurrent runs are serialised with a transaction-scoped advisory lock.
**Consequences:** + reproducible, auditable results; − results of older runs remain until the dataset is reloaded (the loader truncates `ops.match_run` as derived data).

## ADR-024 — Payment block set by the engine via a column-level grant (decision D1)
**Status:** Accepted (2026-11-02)
**Decision:** `eops_app` may `UPDATE (payment_block) ON erp.invoice_header` and nothing else in erp. Each run sets block `R` on unpaid invoices with a blocking exception and clears it elsewhere (paid invoices are never blocked). All other ERP writes stay approval-gated through `eops_action` (ADR-003).
**Consequences:** + realistic (SAP invoice verification blocks automatically) without widening write access; tested in `test_db_roles.py`.

## ADR-025 — Duplicate scoring and threshold tuning on a separate seed (decision D2)
**Status:** Accepted (2026-11-02)
**Decision:** Transparent weighted score: normalized reference 0.45, exact amount 0.25 (close 0.10), dates ≤ 3 days 0.15 (≤ 30 days 0.05), same PO set 0.15. Candidates share the VAT ID (catches duplicate vendor masters), amount within ±0.5 %, invoice date within 30 days; credit memos excluded. Pairs ≥ 0.30 are recorded; ≥ **0.60** are flagged. The threshold was chosen on **seed 7** and reported on **seed 42**.
**Finding:** on seed 7 every threshold from 0.50 to 1.00 is perfect; false positives start at ≤ 0.45 (repeat orders and partial deliveries score 0.30–0.45). 0.60 keeps the largest safety margin. The synthetic duplicates are easy (all score 1.00) — harder variants (re-issued under a new number, amended amounts) are on the backlog so the threshold trade-off becomes measurable.

## ADR-026 — KPI catalog defined once in SQL on the agent views
**Status:** Accepted (2026-11-02)
**Decision:** 12 KPIs live in `app/services/kpis.py` as named SQL definitions (value + sample size, optional supplier breakdown), parameterised by company code and period. They read the `agent` views, so the dashboard (Task 6), the API and the agents (Task 4) report identical numbers. Two KPIs are verified against an independent Python calculation in the tests.
**Consequences:** + one definition per KPI; − money KPIs are per company currency (no FX conversion, by design for v1).
