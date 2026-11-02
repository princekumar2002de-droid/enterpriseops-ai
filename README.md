# EnterpriseOps AI

**Multi-agent ERP intelligence for procurement and invoice exception management.**

EnterpriseOps AI investigates supplier-invoice exceptions the way an experienced accounts-payable analyst would. It runs a deterministic three-way match (purchase order ↔ goods receipt ↔ invoice) on SAP-aligned ERP data, then AI agents explain *why* an invoice was blocked: they combine ERP facts, contract clauses and policy rules with citations, propose a resolution, and wait for a human to approve it before anything changes.

> **Agents reason, services compute, humans approve, the audit log remembers.**

**Status:** Task 2 of 8 — SAP-aligned ERP schema and a seeded synthetic dataset with labeled exceptions. See [`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md).

---

## Quick start

**Prerequisites:** Docker Desktop, [uv](https://docs.astral.sh/uv/) (`brew install uv`), Git.

```bash
cp .env.example .env              # then change POSTGRES_PASSWORD (and the two URLs that contain it)
docker compose up --build         # db -> migrate -> api
```

Then open:
- http://localhost:8000/health/ready — should return `"status": "ready"`
- http://localhost:8000/docs — interactive API documentation

Load the synthetic ERP dataset (≈35,000 rows, 18 months, labeled exceptions):

```bash
cd backend && uv sync
uv run python -m data_generation generate --seed 42 --profile full
```

## Development without Docker for the API

Run only the database in Docker and the API on your machine (fast reload):

```bash
docker compose up -d db
cd backend
uv sync                           # creates .venv from uv.lock
uv run alembic upgrade head       # apply migrations to the dev database
uv run uvicorn app.main:app --reload
```

## Quality checks (same as CI)

```bash
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest --cov               # integration tests run when EOPS_TEST_DATABASE_URL is set (it is in .env)
```

## Repository layout

```
backend/        FastAPI app, data generator (data_generation/), Alembic migrations, tests
infra/          Database init scripts
docs/           Requirements, architecture, schema, agent design, API, roadmap, decisions, log
.github/        CI: lint, types, tests with PostgreSQL+pgvector, secret scan, Docker build
```
Coming later: `documents/` + `evaluation/` (Task 4), `frontend/` (Task 6).

## Documentation

| Document | Content |
|---|---|
| [PROJECT_REQUIREMENTS](docs/PROJECT_REQUIREMENTS.md) | Problem, stakeholders, requirements, use cases, P2P process, KPIs |
| [SYSTEM_ARCHITECTURE](docs/SYSTEM_ARCHITECTURE.md) | Principles, architecture, security, technology choices |
| [DATABASE_SCHEMA](docs/DATABASE_SCHEMA.md) | SAP-aligned data model and migration history |
| [AGENT_DESIGN](docs/AGENT_DESIGN.md) | Agent roadmap, investigation graph, responsibilities |
| [API_DOCUMENTATION](docs/API_DOCUMENTATION.md) | Endpoints and conventions |
| [DEVELOPMENT_ROADMAP](docs/DEVELOPMENT_ROADMAP.md) | 8-task plan, risks, Definition of Done |
| [TESTING_AND_EVALUATION](docs/TESTING_AND_EVALUATION.md) | Test strategy and AI evaluation plan |
| [IMPLEMENTATION_LOG](docs/IMPLEMENTATION_LOG.md) | What was built and verified, task by task |
| [DECISIONS](docs/DECISIONS.md) | Architecture decision records |

## Disclaimer

All ERP data, suppliers, contracts and policies are **synthetic**. The data model is *aligned* with SAP S/4HANA procurement objects; this project does not connect to an SAP system.
