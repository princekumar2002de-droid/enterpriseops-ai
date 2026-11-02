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
**Decision:** Internal tool calls stay in-process. Optionally (week 7), expose the read-only tool registry as an MCP server for external MCP clients.
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
