# EnterpriseOps AI — Project Initiation Package

| | |
|---|---|
| **Project** | EnterpriseOps AI – Multi-Agent ERP Intelligence Platform |
| **Initial domain** | Procurement intelligence & invoice exception management (Procure-to-Pay) |
| **Phase** | 1 — Business requirements & system design |
| **Status** | **APPROVED** 2026-11-02 — baseline. Living versions of each section are maintained in the dedicated documents. |
| **Date** | 2026-11-02 |
| **Owner** | Prince Kumar |

> **Labeling convention used in this whole project** (and enforced later in the agents' output):
> **[FACT]** verified from data/sources · **[CALC]** deterministic calculation · **[INTERP]** interpretation / judgment · **[REC]** recommendation · **[ASSUMPTION]** to be confirmed.

---

## 0. The five design principles (read this first)

These five principles drive almost every decision below. Several of them deliberately push back on the initial project brief.

1. **Agents reason, services compute, humans approve, the audit log remembers.**
   An LLM must never be the component that *decides* whether an invoice matches. Three-way matching, duplicate scoring and KPI calculation are **deterministic code with unit tests**. The LLM investigates, explains, retrieves policy context and drafts recommendations on top of those results.
2. **Smallest architecture that works, expanded only on evidence.** The brief lists 7 agents. We start with **one investigation agent plus deterministic workflow nodes**, then split into specialists *only when evaluation shows a single agent degrading* (tool-selection errors, context bloat). Agent count is not a quality metric; measured task success is.
3. **No number without a source.** Every figure in an agent answer must come from a tool result (and is checked automatically). Every policy claim must carry a document citation.
4. **Agents have no write tools.** Agents can only *propose* actions. A separate, non-LLM Action Service executes approved actions with idempotency keys, role checks and audit records.
5. **Ground truth by construction.** The synthetic ERP data is generated with **seeded, labeled exceptions**, so we can measure the precision/recall of matching and agents instead of eyeballing demos.

---

## 1. Executive summary

Accounts-payable (AP) teams spend a large share of their time on invoices that fail automatic matching against purchase orders and goods receipts. Each blocked invoice triggers manual detective work across the ERP system, email threads, supplier contracts and procurement policies. That work is slow, inconsistent and hard to audit, and late resolution costs cash discounts and damages supplier relationships.

**EnterpriseOps AI** is a decision-support and workflow platform for this problem. It combines:

- a **deterministic matching engine** (three-way match, tolerance checks, duplicate detection) that runs on an SAP-aligned ERP data model;
- an **AI investigation layer** (LangGraph-orchestrated Claude agents) that explains *why* an invoice was flagged, pulls in the relevant contract clauses and policy rules with citations, analyzes supplier history and proposes a resolution;
- a **human-in-the-loop action workflow** (approve/reject, role-based limits, four-eyes principle) with a tamper-evident audit trail;
- an **evaluation harness** that measures matching accuracy, retrieval quality, grounding/hallucination, task success, latency and cost.

The product is "SAP-aligned, not SAP-integrated". The data model and adapter interface mirror S/4HANA procurement objects and APIs, so a real connector is a documented next step. It is not a claim of a working SAP integration.

**Portfolio value:** it shows end-to-end enterprise AI engineering: business process analysis, data engineering, RAG with traceable sources, reliable tool calling, durable agent workflows with approvals, security controls and *measured* AI quality.

---

## 2. Business problem statement

**Context.** In Procure-to-Pay (P2P), a supplier invoice should only be paid if it matches what was ordered (purchase order, PO) and what was received (goods receipt, GR). This is the *three-way match*. In SAP this happens in Logistics Invoice Verification (transaction MIRO / the Supplier Invoice app), where configurable tolerance limits decide whether variances block the invoice for payment.

**Problem.** When an invoice is blocked, the AP clerk must:
1. find the PO, GR history and previous invoices for the PO line;
2. work out *which* variance caused the block (price, quantity, missing GR, duplicate suspicion, and so on);
3. check the supplier contract (agreed prices, price-adjustment clauses, payment terms) and internal policy (tolerances, approval limits);
4. check the supplier's history (is this a pattern?);
5. decide on a resolution (release the block, request a credit memo, wait for the GR, escalate) and document it.

Today this is manual, spread across systems, inconsistent between clerks and weakly documented. **Consequences:** long exception cycle times, lost early-payment discounts, duplicate-payment leakage, late-payment friction with suppliers, and poor visibility for procurement on which suppliers and processes cause the exceptions.

**Problem statement (one sentence).** *AP and procurement teams lack a fast, consistent and auditable way to investigate and resolve invoice exceptions using both structured ERP data and unstructured contracts and policies.*

---

## 3. Business objectives

The baselines and targets below are for the **simulated environment**. They are demo targets measured on our synthetic dataset, not claims about real companies. **[ASSUMPTION]**

| ID | Objective | KPI (formula in §8.4) | Target (simulated) |
|---|---|---|---|
| BO-1 | Detect all invoice exceptions reliably | Matching precision / recall vs. seeded labels | ≥ 0.99 / ≥ 0.99 (deterministic engine) |
| BO-2 | Cut investigation effort per exception | Time-to-explanation (agent) | p95 < 45 s per investigation |
| BO-3 | Prevent duplicate payments | Duplicate detection recall at chosen threshold; € value prevented | Recall ≥ 0.95, precision ≥ 0.85 |
| BO-4 | Make recommendations trustworthy | Grounded-number rate; citation accuracy | 100 % numbers traceable; ≥ 90 % citations support the claim |
| BO-5 | Keep humans in control | Unapproved write actions executed | **0** (hard requirement) |
| BO-6 | Give procurement supplier insight | Supplier OTIF, discrepancy rate, avg. delay available per supplier/period | Available via dashboard and agent |
| BO-7 | Operate economically | LLM cost per investigation | < €0.10 average **[ASSUMPTION — validate in week 5]** |

---

## 4. Stakeholder analysis

| Stakeholder | Role in P2P | Interest / pain | Influence | How the system serves them | System role (RBAC) |
|---|---|---|---|---|---|
| AP Clerk | Processes and resolves invoices | Too much manual investigation | Medium | Explained exceptions, evidence pack, drafted resolutions | `AP_CLERK` |
| AP Team Lead | Approves resolutions, owns AP KPIs | Backlog, cycle time, discount loss | High | Approval queue, KPI dashboard, four-eyes control | `AP_MANAGER` |
| Buyer / Purchaser | Creates POs, owns supplier relationship | Gets pulled into disputes late | Medium | Supplier follow-up drafts, PO-related root causes | `BUYER` |
| Procurement / Category Manager | Supplier strategy, contracts | No data on supplier reliability | High | Supplier performance and risk analysis | `PROCUREMENT_MANAGER` |
| Warehouse / Goods Receiving | Posts goods receipts | Late GR postings cause blocks | Low | Bottleneck analysis exposes GR delays | (read via reports) |
| Controller / Finance Manager (CFO office) | Cash, working capital, compliance | Duplicate payments, discount capture | High | Financial KPIs, € at risk | `FINANCE_VIEWER` |
| Internal Audit / Compliance | Controls, SoD | Need traceable decisions | High | Immutable audit log, decision rationale | `AUDITOR` (read-only) |
| Supplier | Gets paid | Late payment, unclear disputes | Low (external) | Clear, fact-based follow-up messages | none |
| IT / ERP team | Runs SAP and integrations | Security, stability, no uncontrolled writes | High | Read-only by default, adapter boundary, no free SQL | `ADMIN` |
| Data Protection Officer | GDPR | Personal data in supplier contacts | Medium | Synthetic data, minimization, no PII to the LLM where avoidable | n/a |
| *Portfolio audience* (recruiters, professors) | Evaluate you | Real engineering, not a toy chatbot | — | README, architecture, evaluation report, demo | n/a |

**Segregation of duties (SoD):** the person (or agent) who *proposes* an action can never be the one who *approves* it. Approval limits are tied to role and amount (see FR-WF-04).

---

## 5. Functional requirements

Priority uses MoSCoW: **M**ust / **S**hould / **C**ould / **W**on't (this release).

### 5.1 ERP data & matching (deterministic core)
| ID | Requirement | Prio |
|---|---|---|
| FR-DM-01 | Store SAP-aligned master and transactional data: suppliers, materials, POs (header/item), contracts, goods receipts (incl. reversals), supplier invoices (header/item), payments. | M |
| FR-DM-02 | Run a **three-way match** per invoice line: PO ↔ GR ↔ invoice, with GR-based invoice verification logic (invoiced qty ≤ received qty − previously invoiced qty). | M |
| FR-DM-03 | Apply configurable **tolerance rules** (percentage *and* absolute, upper/lower), modeled on SAP tolerance keys (price variance, quantity variance, small-difference). | M |
| FR-DM-04 | Classify exceptions with a fixed taxonomy (§8.3) and severity, and compute **amount at risk** in EUR. | M |
| FR-DM-05 | Detect **duplicate invoices**: exact rule (same supplier + reference + amount + date) and fuzzy scoring (normalized reference, amount, date window, same VAT ID/IBAN under a different supplier ID). | M |
| FR-DM-06 | Set a simulated **payment block** on invoices that fail matching; keep a block reason per invoice. | M |
| FR-DM-07 | Re-run matching idempotently (each run is versioned; results reproducible). | M |
| FR-DM-08 | Detect risky master-data events (supplier bank-account change shortly before invoice), a known fraud pattern. | S |
| FR-DM-09 | Check invoice payment terms and prices against contract terms (structured contract items). | S |

### 5.2 Analytics & KPIs
| ID | Requirement | Prio |
|---|---|---|
| FR-AN-01 | Calculate the KPI catalog (§8.4) by period, supplier, company code and material group via **predefined, parameterized queries**. | M |
| FR-AN-02 | Supplier performance: OTIF, avg. delivery delay, discrepancy rate, exception value, trend. | M |
| FR-AN-03 | Process bottlenecks: stage lead times (PO→GR, GR→invoice, invoice→posting, block→release), backlog ageing. | S |
| FR-AN-04 | Supplier risk score (transparent, rule-based weighted score, with its factors shown). | S |
| FR-AN-05 | Monthly procurement performance report (generated, with an AI narrative clearly labeled). | S |

### 5.3 Document intelligence (RAG)
| ID | Requirement | Prio |
|---|---|---|
| FR-DI-01 | Ingest contracts, procurement policies and AP procedures (PDF/Markdown) with metadata: doc type, supplier, version, validity dates. | M |
| FR-DI-02 | Hybrid retrieval (vector + full-text), filtered by supplier, doc type and validity date. | M |
| FR-DI-03 | Every retrieved passage carries a **citation** (document, version, section, page). | M |
| FR-DI-04 | Only the currently valid contract version is used unless the user asks for history. | S |
| FR-DI-05 | OCR/extraction of scanned supplier invoices. | **W** (see §14) |

### 5.4 AI agents
| ID | Requirement | Prio |
|---|---|---|
| FR-AG-01 | Answer natural-language questions about invoices, suppliers, KPIs and policies using tools only (no direct DB access). | M |
| FR-AG-02 | **Investigate an invoice exception** end-to-end and return a structured finding: facts, calculations, interpretations, recommendation, confidence, citations. | M |
| FR-AG-03 | Separate output into [FACT]/[CALC]/[INTERP]/[REC] in both the API schema and the UI. | M |
| FR-AG-04 | Refuse or escalate when evidence is missing or conflicting, instead of guessing. | M |
| FR-AG-05 | Stream progress (which tools are running) to the UI. | S |
| FR-AG-06 | Remember conversation context within a session (thread). | S |
| FR-AG-07 | Constrained ad-hoc analytics ("text-to-SQL") over curated read-only views with AST validation. | C |
| FR-AG-08 | Expose the read-only tool layer as an **MCP server** for external MCP clients. | C |

### 5.5 Workflow, approval & audit
| ID | Requirement | Prio |
|---|---|---|
| FR-WF-01 | Agents create **action proposals** only (release block, request credit memo, request GR posting, send supplier inquiry, escalate). | M |
| FR-WF-02 | Approval UI/API: approve, reject (with reason) or edit-then-approve. The workflow pauses durably until a decision is made. | M |
| FR-WF-03 | Approved actions are executed by a deterministic Action Service with an idempotency key; results are written back to the simulated ERP. | M |
| FR-WF-04 | Role- and amount-based approval limits and four-eyes principle (proposer ≠ approver). | M |
| FR-WF-05 | Append-only, hash-chained **audit log** for every human, agent and system action (who, what, when, before/after, trace ID). | M |
| FR-WF-06 | Generate supplier follow-up messages as drafts. They are never sent automatically. | S |

### 5.6 Frontend
| ID | Requirement | Prio |
|---|---|---|
| FR-UI-01 | KPI dashboard (match rate, exceptions by type, € at risk, supplier ranking). | M |
| FR-UI-02 | Exception worklist with filters; invoice detail with PO/GR/invoice side-by-side. | M |
| FR-UI-03 | Investigation view: evidence, labeled findings, citations (click to open the source passage). | M |
| FR-UI-04 | Approval queue. | M |
| FR-UI-05 | Chat interface with tool-progress streaming. | S |
| FR-UI-06 | Audit log viewer. | S |

---

## 6. Non-functional requirements

| ID | Category | Requirement | How verified |
|---|---|---|---|
| NFR-SEC-01 | Security | No secrets in code; `.env` + environment variables; `.env` in `.gitignore`; secret scanning in CI. | CI check (gitleaks) |
| NFR-SEC-02 | Security | The agent DB role is **read-only** on curated views; writes only through the Action Service role. | Integration test tries a write as the agent role → must fail |
| NFR-SEC-03 | Security | The LLM cannot run arbitrary SQL or shell commands. Tools are typed, parameterized and allow-listed. | Code review + tests |
| NFR-SEC-04 | Security | Retrieved documents and ERP text fields are treated as **untrusted data** (prompt-injection defense: delimiting, no write tools, approval gate). | Injection test scenarios (≥ 10) |
| NFR-SEC-05 | Security | Authentication (JWT) and RBAC enforced at API **and** tool level (tools receive the user context). | Authorization test suite |
| NFR-AUD-01 | Auditability | 100 % of state-changing operations produce an audit event; the audit table is append-only (DB permissions + trigger) and hash-chained. | Test + verification script |
| NFR-REL-01 | Reliability | LLM/API calls: timeouts, retries with exponential backoff for retryable errors, max-iteration and token budgets per run. | Fault-injection tests |
| NFR-REL-02 | Reliability | Durable workflows: a pending approval survives an API restart (Postgres checkpointer). | Restart test |
| NFR-REL-03 | Reliability | Action execution is idempotent (no double credit memo on retry). | Test |
| NFR-PERF-01 | Performance | Deterministic matching of 10k invoice lines < 30 s; dashboard API p95 < 500 ms. | Benchmark script |
| NFR-PERF-02 | Performance | Agent investigation p95 < 45 s; first streamed token < 3 s. | Eval harness |
| NFR-EXP-01 | Explainability | Each finding is labeled FACT/CALC/INTERP/REC; every number traces to a tool result; every policy claim has a citation. | Automated grounding check |
| NFR-COST-01 | Cost | Per-run token budget; cheaper model for routing/classification; prompt caching for static prompts/tools; cost logged per run. | Eval report |
| NFR-OBS-01 | Observability | Structured JSON logs with `trace_id`; LLM traces (LangSmith); per-run metrics (latency, tokens, tools called). | Manual + dashboard |
| NFR-MAINT-01 | Maintainability | Layered modules, type hints, Pydantic models, ruff + mypy in CI, ≥ 80 % coverage on the deterministic core. | CI |
| NFR-TEST-01 | Testability | **Unit tests never call the real LLM.** Agent tests use recorded/mocked responses; live evals run separately. | CI configuration |
| NFR-PRIV-01 | Privacy | Synthetic data only; no real personal data; supplier contact names are fictitious. | Data generator review |
| NFR-PORT-01 | Portability | `docker compose up` brings up the full stack locally; the LLM provider sits behind an interface. | Fresh-clone test |

---

## 7. Detailed use cases

### 7.1 Use-case overview

```mermaid
flowchart LR
  clerk([AP Clerk]); mgr([AP Manager]); proc([Procurement Mgr]); aud([Auditor]); sys([Scheduler / System])
  subgraph EnterpriseOps AI
    UC1[UC-01 Three-way match invoices]
    UC2[UC-02 Detect price/qty discrepancies]
    UC3[UC-03 Detect duplicate invoices]
    UC4[UC-04 Analyze supplier delivery performance]
    UC5[UC-05 Identify process bottlenecks]
    UC6[UC-06 Retrieve contract & policy rules]
    UC7[UC-07 Investigate invoice exception]
    UC8[UC-08 Analyze supplier risk]
    UC9[UC-09 Recommend decision]
    UC10[UC-10 Approve & execute action]
  end
  sys --> UC1 --> UC2
  UC1 --> UC3
  clerk --> UC7
  UC7 -.include.-> UC2
  UC7 -.include.-> UC6
  UC7 -.include.-> UC8
  UC7 -.include.-> UC9
  UC9 -.extend.-> UC10
  mgr --> UC10
  proc --> UC4
  proc --> UC5
  proc --> UC8
  clerk --> UC6
  aud --> UC10
```

### 7.2 Use-case specifications

**UC-01 — Three-way match invoices** (deterministic)
- **Actor:** System (scheduled or on invoice arrival); AP Clerk (manual re-run)
- **Preconditions:** Invoice exists with PO references; tolerance rules are configured.
- **Main flow:** 1) Load invoice lines. 2) For each line, resolve the PO item and cumulative GR qty (receipts minus reversals) and the previously invoiced qty. 3) Compute quantity variance = invoiced qty − (GR qty − previously invoiced qty). 4) Compute price variance = (invoice unit price − PO net price per price unit) × qty. 5) Apply tolerance rules. 6) Write a `match_result` per line and `exception`s; set a payment block if any line is blocking.
- **Alternatives:** No GR yet → `NO_GOODS_RECEIPT` (if GR-based IV); no PO reference → `NO_PO_REFERENCE`; currency differs → `CURRENCY_MISMATCH`; PO item flagged as fully invoiced → `PO_OVER_INVOICED`.
- **Postconditions:** Each invoice has status `MATCHED`, `MATCHED_WITHIN_TOLERANCE` or `BLOCKED`, with reasons. The run is versioned.
- **Business rule source:** policy document "AP Tolerance Policy" + `tolerance_rule` table (the two are kept consistent).

**UC-02 — Detect price and quantity discrepancies.** Sub-function of UC-01 exposed as a query: "Which invoices don't match their POs?" Returns exceptions with variance amounts, % and tolerance applied. **Actor:** Clerk / Procurement Mgr. **Output:** [CALC] table.

**UC-03 — Identify duplicate invoices**
- **Main flow:** 1) Normalize the supplier reference (strip spaces/punctuation/leading zeros, upper-case). 2) Generate candidate pairs: same supplier *or* same VAT ID/IBAN; amount within ±0.5 %; invoice date within 30 days. 3) Score the pair (weighted features). 4) Above threshold → `DUPLICATE_SUSPECTED` with the matched invoice ID and feature breakdown.
- **Alternatives:** A credit memo with the same reference is not a duplicate. A reversed invoice is excluded.
- **Postconditions:** Suspected duplicates are blocked and show "€ prevented if confirmed".

**UC-04 — Analyze supplier delivery performance.** Actor: Procurement Mgr. Question: "Which suppliers have the highest delivery delays?" → `compute_kpi(OTIF, avg_delay_days by supplier, period)` → ranked [CALC] table + [INTERP] commentary (e.g., "delays concentrate in Q3 and in material group X").

**UC-05 — Identify procurement process bottlenecks.** Actor: Procurement Mgr / AP Lead. Stage lead-time distributions (PO→GR, GR→IR, IR→posting, block→release) + backlog ageing → [CALC], with an [INTERP] naming the dominant bottleneck and [REC] process changes.

**UC-06 — Retrieve contract and procurement policy rules.** Actor: Clerk. "What does our policy say about price variances above 5 %?" → hybrid retrieval filtered by doc type/validity → answer **only** from retrieved passages, with citations; if nothing relevant is found, say so.

**UC-07 — Investigate an invoice exception** (flagship use case)
- **Actor:** AP Clerk. **Trigger:** "Why is invoice 5105600123 flagged?" or the "Investigate" button.
- **Preconditions:** The invoice has ≥ 1 exception; the user has `AP_CLERK` or a higher role.
- **Main flow:** 1) Load the case: invoice, match result and exceptions [FACT/CALC]. 2) Gather evidence: PO, GR history, prior invoices on the PO, duplicate candidates. 3) Retrieve the supplier contract terms and tolerance policy [FACT + citation]. 4) Supplier context: discrepancy history, OTIF, recent bank changes [CALC]. 5) Produce a structured finding: root-cause hypothesis [INTERP], recommendation [REC] (e.g., "Request credit memo for €412.50 price difference — contract §4.2 fixes the unit price at €18.20"), confidence and open questions. 6) Grounding check passes. 7) Propose an action → UC-10.
- **Alternatives:** Conflicting evidence → recommend "escalate" with the conflict listed. Missing contract → state the gap; no fabricated terms. Tool failure → partial result marked incomplete.
- **Postconditions:** A `case_finding` is stored and an `action_request` is created as PENDING. Everything is audited.

**UC-08 — Analyze supplier risk.** Rule-based, transparent score from: discrepancy rate, OTIF, duplicate attempts, bank-detail changes, spend concentration, contract expiry. The [CALC] score shows each factor's contribution; the agent adds an [INTERP] narrative. *No black-box ML in v1* (it isn't explainable and we have no labeled real-world risk outcomes).

**UC-09 — Recommend a business decision.** "Should we approve or investigate this invoice?" The synthesis step combines UC-07 evidence into approve / request correction / hold / escalate, with the decisive facts, the risks of each option and the € impact (incl. discount deadline). **It never executes anything.**

**UC-10 — Approve and execute an action (human-in-the-loop)**
- **Actors:** AP Manager (approver), Action Service (executor), Auditor (reviewer).
- **Main flow:** 1) The workflow pauses (durable interrupt) with the proposal shown. 2) The approver checks the role/amount limit and four-eyes rule → approve / reject / edit. 3) On approval, the Action Service executes with an idempotency key (e.g., release payment block, create credit-memo request, create supplier-inquiry draft). 4) The simulated ERP is updated; an audit event is written; the case closes or continues.
- **Alternatives:** Reject → reason is stored; the agent may revise once. Limit exceeded → route to a higher role. Execution fails → status FAILED, retry-safe.
- **Postconditions:** Executed exactly once, or not at all; fully audited.

---

## 8. Procurement business process

### 8.1 Procure-to-Pay (P2P) process — to-be with EnterpriseOps AI

```mermaid
flowchart TD
  A[Purchase requisition] --> B{PR approval}
  B -->|approved| C[Purchase order<br/>EKKO/EKPO]
  C --> D[Supplier order confirmation]
  D --> E[Goods receipt<br/>mvt type 101 → MATDOC]
  C --> F[Supplier invoice received<br/>RBKP/RSEG]
  E --> G
  F --> G[[Deterministic 3-way match<br/>+ duplicate check]]
  G -->|match / within tolerance| H[Post invoice]
  G -->|variance / dup / no GR| I[Payment block + exception case]
  I --> J[[AI investigation<br/>evidence · citations · recommendation]]
  J --> K{Human approval<br/>role & amount limits}
  K -->|release block| H
  K -->|request credit memo| L[Supplier inquiry / credit memo] --> G
  K -->|wait for GR| E
  K -->|escalate| M[Buyer / Procurement]
  H --> N[Payment run<br/>discount deadline] --> O[Payment]
  J -. KPIs .-> P[(Supplier & process analytics)]
```

### 8.2 Three-way matching logic (business rules)

Matching runs **per invoice line against a PO item**. The core comparisons:

| Check | Formula | Exception code | Typical SAP analogue |
|---|---|---|---|
| Quantity | `inv_qty − (Σ GR qty − Σ GR reversals − Σ previously invoiced qty)` > tolerance | `QTY_VARIANCE` | Tolerance key **DQ** (quantity variance) |
| Missing GR | GR-based IV and Σ GR qty = 0 | `NO_GOODS_RECEIPT` | GR-based IV flag on PO item |
| Price | `(inv_unit_price − po_net_price / price_unit) × inv_qty` outside the % and absolute tolerance | `PRICE_VARIANCE` | Tolerance key **PP** (price variance) |
| Small difference | Total difference ≤ small-difference limit → auto-accept | (accepted) | Tolerance key **BD** |
| Over-invoicing | Σ invoiced qty on PO item > PO qty | `PO_OVER_INVOICED` | — |
| Contract price | PO net price > valid contract price | `CONTRACT_PRICE_DEVIATION` | Outline agreement |
| Payment terms | Invoice terms ≠ PO/contract terms | `PAYMENT_TERMS_MISMATCH` | — |
| Currency | Invoice currency ≠ PO currency | `CURRENCY_MISMATCH` | — |
| No PO | Invoice line without PO reference | `NO_PO_REFERENCE` | Tolerance key **AN** (non-PO items) |
| Duplicate | Duplicate score ≥ threshold | `DUPLICATE_SUSPECTED` | SAP duplicate-invoice check (supplier, reference, date, amount, company code) |
| Fraud signal | Supplier bank details changed ≤ 30 days before invoice | `BANK_DETAILS_CHANGED` | — |

**Tolerance rule model:** `(company_code, tolerance_key, lower_abs, upper_abs, lower_pct, upper_pct)`. An exception is raised if **either** the absolute **or** the percentage limit is breached (this mirrors how SAP limits are typically configured; see Open Question Q9). **[ASSUMPTION]** Default demo values: price ±2 % / ±€100 per line; quantity: no over-delivery tolerance; small difference €5.

**Precision rules:** all money is stored as `NUMERIC(15,2)` (prices `NUMERIC(15,4)`), **never float**. Comparisons happen in the PO currency; multi-currency conversion is out of scope for the MVP (EUR + one foreign currency for the `CURRENCY_MISMATCH` case).

### 8.3 Exception taxonomy and severity

| Code | Severity rule | Blocks payment |
|---|---|---|
| `DUPLICATE_SUSPECTED` | Critical | Yes |
| `BANK_DETAILS_CHANGED` | Critical | Yes |
| `PRICE_VARIANCE` | High if > €1,000 or > 10 %, else Medium | Yes |
| `QTY_VARIANCE` / `NO_GOODS_RECEIPT` | High / Medium | Yes |
| `PO_OVER_INVOICED` | High | Yes |
| `NO_PO_REFERENCE` | Medium (needs an approval flow) | Yes |
| `CONTRACT_PRICE_DEVIATION` | Medium (procurement issue) | No (flag only) |
| `PAYMENT_TERMS_MISMATCH` | Low | No (flag only) |
| `CURRENCY_MISMATCH` | High | Yes |

### 8.4 KPI catalog

**Business KPIs** (calculated deterministically by SQL; definitions are version-controlled):

| KPI | Formula | Owner | Why it matters |
|---|---|---|---|
| First-pass match rate (touchless rate) | invoices posted without manual intervention / all invoices | AP Lead | Main AP efficiency KPI |
| Exception rate by type | invoices with exception type X / all invoices | AP Lead | Root-cause focus |
| Exception value at risk | Σ amount at risk of open exceptions (€) | Controller | Financial exposure |
| Avg. exception resolution time | mean(release_ts − block_ts) | AP Lead | Cycle time |
| Invoice cycle time | median(posting_date − receipt_date) | AP Lead | Process speed |
| Cash-discount capture rate | discount taken / discount available | Controller | Direct € value of faster resolution |
| Late-payment rate | invoices paid after due date / paid invoices | Controller | Supplier relationship |
| Duplicate value prevented | Σ gross amount of confirmed duplicates blocked | Controller | Leakage prevention |
| Supplier OTIF | GR lines on time **and** in full / all GR lines | Procurement | Supplier reliability |
| Avg. delivery delay | mean(max(0, GR date − promised date)) | Procurement | Supplier reliability |
| Supplier discrepancy rate | supplier invoices with ≥ 1 exception / supplier invoices | Procurement | Supplier quality |
| Price variance % | Σ price variance / Σ invoiced value | Procurement | Contract compliance |
| Non-PO invoice share | invoices without PO / all invoices | Procurement | Maverick buying indicator |
| PO→GR lead time, GR→IR lag | median day differences | Process owner | Bottlenecks |

**AI / system KPIs** (measured by the evaluation harness, Phase 7):

| KPI | Measurement |
|---|---|
| Matching precision / recall | vs. seeded exception labels |
| Duplicate detection precision / recall @ threshold | vs. seeded duplicates (incl. hard negatives) |
| Retrieval Recall@5, MRR | vs. a labeled question→passage set |
| Citation accuracy | % of cited passages that actually support the claim (LLM-judge + manual sample) |
| Grounded-number rate | % of numbers in answers that appear in tool outputs (automatic check) |
| Tool-selection accuracy | correct tool + valid args on labeled scenarios |
| Task success rate | scenario rubric pass rate (50–100 scenarios) |
| Unsafe-action rate | write actions without approval (must be 0) |
| Injection resistance | % of injection scenarios with no policy violation |
| Latency p50/p95, tokens and € per run | from traces |

---

## 9. Proposed system architecture

### 9.1 Logical architecture

```mermaid
flowchart TB
  subgraph Client
    UI[React + TS dashboard<br/>worklist · investigation · approvals · chat]
    MCPC[External MCP client<br/>optional]
  end
  subgraph API["FastAPI (REST + SSE)"]
    AUTH[AuthN JWT / RBAC]
    R1[/invoices, exceptions, kpis/]
    R2[/agent/runs · stream/]
    R3[/approvals/]
  end
  subgraph AgentLayer["Agent layer (LangGraph)"]
    G[Investigation graph<br/>deterministic nodes + LLM agent node]
    TOOLS[Typed tool registry<br/>read-only + propose_action]
  end
  subgraph Services["Domain services (no LLM)"]
    MATCH[Matching engine]
    DUP[Duplicate detector]
    KPI[KPI / analytics service]
    RET[Retrieval service<br/>hybrid search]
    CASE[Case service]
    ACT[Action service<br/>approval-gated writes]
    AUDIT[Audit service]
  end
  subgraph Data["PostgreSQL 17 + pgvector"]
    ERP[(erp schema<br/>SAP-aligned)]
    OPS[(ops schema<br/>matches, cases, actions)]
    DOCS[(docs schema<br/>chunks + embeddings + tsvector)]
    AUD[(audit schema<br/>append-only)]
    CKPT[(LangGraph checkpoints)]
  end
  LLM[[Claude API]]
  EMB[[Embedding model]]
  OBS[[Structured logs + LangSmith traces]]
  ADP[ERP adapter interface<br/>Simulated ↔ future S/4HANA OData]

  UI --> API
  API --> AgentLayer
  API --> Services
  G --> TOOLS --> Services
  G <--> LLM
  RET --> EMB
  MCPC -.-> TOOLS
  Services --> Data
  G --> CKPT
  ADP --> ERP
  AgentLayer -.-> OBS
```

### 9.2 Key architecture decisions (summary — full ADRs in `DECISIONS.md`)

| # | Decision | Why | Alternative rejected |
|---|---|---|---|
| ADR-001 | **Deterministic matching engine; LLM only explains** | Matching is a financial control: it must be exact, reproducible and testable. LLMs are probabilistic. | "Agent does the 3-way match" — non-reproducible, unauditable |
| ADR-002 | **Start with 1 agent + deterministic nodes; split on evidence** | LangChain's own multi-agent guidance: a single agent with good tools often suffices; multi-agent pays off when tools/prompts grow too large. Fewer calls = lower latency and cost. | 7 agents from day 1 |
| ADR-003 | **Agents have no write tools**; `propose_action` + approval interrupt + Action Service | Removes the whole class of "LLM did something unauthorized", including via prompt injection | Workflow Execution *Agent* with write tools |
| ADR-004 | **Typed, parameterized tool catalog instead of text-to-SQL** (text-to-SQL only as a later, constrained "C" feature) | Brief requires no arbitrary SQL; typed tools are testable and permissionable | Free text-to-SQL |
| ADR-005 | **LangGraph for orchestration, official `anthropic` SDK inside nodes** | LangGraph gives durable state, checkpointing and `interrupt()` for HITL; the raw SDK gives full control of strict tool use, prompt caching and model features without wrapper lag | LangChain model wrappers everywhere; a hand-rolled loop (no durable HITL) |
| ADR-006 | **PostgreSQL for everything** (ERP data, vectors via pgvector, FTS, checkpoints, audit) | One system to operate; transactional consistency between cases, actions and audit; pgvector supports HNSW + filtering; hybrid search with FTS | Separate vector DB (Pinecone/Qdrant) — unnecessary at this scale |
| ADR-007 | **SAP-aligned data model + ERP adapter interface** | Realistic and recognizable to SAP people; a clear path to real OData integration | Generic toy schema; claiming SAP integration we don't have |
| ADR-008 | **Seeded synthetic data with ground-truth labels** | Enables quantitative evaluation | Random data, no labels |
| ADR-009 | **MCP as an *outer* interface, not the internal transport** | Internal tool calls are in-process Python (fast, typed). MCP adds value by exposing the read-only tools to external clients (e.g., Claude Desktop) — a nice demonstration of the standard. | Routing internal agent calls through MCP (added latency and complexity, no benefit) |
| ADR-010 | **Pandas only offline** (data generation, reports); aggregation in SQL | Request path stays fast and the logic stays in one place | Pandas in API endpoints |

### 9.3 Proposed repository structure (structure only — no code yet)

```
enterpriseops-ai/
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI routers (thin)
│   │   ├── core/           # config, security, logging
│   │   ├── domain/         # Pydantic models, enums, exception taxonomy
│   │   ├── services/       # matching, duplicates, kpi, retrieval, actions, audit
│   │   ├── adapters/       # erp_adapter (simulated; future s4hana_odata), llm, embeddings
│   │   ├── agents/         # LangGraph graphs, nodes, prompts, tool registry
│   │   ├── db/             # SQLAlchemy models, sessions, views
│   │   └── mcp/            # optional MCP server (read-only tools)
│   ├── migrations/         # Alembic
│   └── tests/              # unit / integration / agent (mocked)
├── data_generation/        # synthetic ERP generator + seeded labels
├── documents/              # sample contracts & policies (source of RAG corpus)
├── evaluation/             # datasets, runners, reports
├── frontend/               # React + TS + Tailwind + Recharts
├── docs/                   # the 9 project documents + ADRs + diagrams
├── docker-compose.yml
└── .github/workflows/
```

### 9.4 Security architecture (defense in depth)

1. **Identity:** JWT with demo users per role (no external IdP in v1).
2. **API layer:** RBAC dependency on each route.
3. **Tool layer:** each tool checks the role from the run context (an agent acting for an `AP_CLERK` can't call `PROCUREMENT_MANAGER`-only tools).
4. **Database layer:** three Postgres roles — `eops_agent_ro` (SELECT on curated views only, `statement_timeout`), `eops_app` (application services), `eops_action` (ERP writes). The audit table: INSERT only; UPDATE/DELETE revoked; hash chain.
5. **LLM layer:** untrusted content wrapped in delimiters and labeled as data; system prompt states that documents never contain instructions; no write tools; output validated against Pydantic schemas (strict tool use); grounding check before results are shown.
6. **Approval layer:** four-eyes principle, amount limits, idempotent execution.

---

## 10. Initial database entities and relationships

Four schemas separate concerns and permissions: `erp` (the simulated source system, SAP-aligned), `ops` (EnterpriseOps' own results and workflow), `docs` (RAG corpus), `audit`. LangGraph checkpoint tables live in their own schema, managed by the checkpointer library.

### 10.1 Entity list with SAP mapping

| Schema.Entity | Key attributes | SAP analogue |
|---|---|---|
| `erp.company_code` | code, name, currency | T001 |
| `erp.supplier` | supplier_id, name, country, vat_id, payment_terms, created_at, blocked | LFA1 / Business Partner |
| `erp.supplier_bank_account` | supplier_id, iban_masked, iban_hash, valid_from, changed_by | LFBK / BP bank |
| `erp.material` | material_id, description, material_group, base_uom | MARA |
| `erp.contract_header` / `contract_item` | contract_id, supplier_id, valid_from/to, document_id → `docs.document`; item: material_id, agreed_price, currency, price_unit | EKKO/EKPO (doc. category K) |
| `erp.purchase_order_header` | po_number, supplier_id, company_code, purch_org, created_at, created_by, currency, payment_terms | EKKO |
| `erp.purchase_order_item` | (po_number, item_no), material_id, qty, uom, net_price, price_unit, promised_delivery_date, gr_based_iv, contract ref, deletion_flag | EKPO / EKET |
| `erp.goods_receipt` | (mat_doc, year, line), po_number, po_item, movement_type (101/102), qty, posting_date, plant | MATDOC (MSEG) |
| `erp.invoice_header` | invoice_id, supplier_id, company_code, supplier_reference, invoice_date, received_date, posting_date, gross/net/tax, currency, payment_terms, payment_block, status, doc_type (invoice / credit memo) | RBKP |
| `erp.invoice_item` | (invoice_id, item_no), po_number, po_item, qty, amount, unit_price, tax_code | RSEG |
| `erp.payment` | payment_id, invoice_id, payment_date, amount, discount_taken | BSAK / payment run |
| `erp.inventory_level` | material_id, plant, qty, as_of (minimal — no v1 use case needs more) | MARD |
| `ops.tolerance_rule` | company_code, tolerance_key, lower/upper abs & pct, policy document ref | OMR6 config |
| `ops.match_run` | run_id, started_at, engine_version, params hash | — |
| `ops.match_result` | run_id, invoice_id, item_no, status, qty_variance, price_variance, tolerance_applied | — |
| `ops.exception` | exception_id, invoice_id, item_no, code, severity, amount_at_risk, status, detected_run_id | — |
| `ops.duplicate_candidate` | invoice_id, candidate_invoice_id, score, feature_breakdown (JSONB) | — |
| `ops.case` | case_id, invoice_id, status, assigned_to, opened/closed_at | — |
| `ops.case_finding` | case_id, agent_run_id, facts/calcs/interps/recs (JSONB, schema-validated), citations, confidence, model, prompt_version | — |
| `ops.action_request` | action_id, case_id, type, payload, status (PENDING/APPROVED/REJECTED/EXECUTED/FAILED), proposed_by, approved_by, amount, idempotency_key | — |
| `ops.agent_run` | run_id, thread_id, user_id, started/ended, tokens_in/out, cost_eur, latency_ms, outcome | — |
| `docs.document` | document_id, doc_type (CONTRACT/POLICY/PROCEDURE), supplier_id?, title, version, valid_from/to, checksum, source_uri | DMS |
| `docs.chunk` | chunk_id, document_id, section_path, page, text, tsv (tsvector), embedding (vector) | — |
| `audit.audit_event` | event_id, ts, actor_type (HUMAN/AGENT/SYSTEM), actor_id, action, entity_type, entity_id, before/after (JSONB), trace_id, prev_hash, hash | — |
| `iam.app_user` / `iam.role` | user_id, role, approval_limit_eur | — |

### 10.2 Core ER diagram

```mermaid
erDiagram
  SUPPLIER ||--o{ PURCHASE_ORDER_HEADER : receives
  SUPPLIER ||--o{ INVOICE_HEADER : issues
  SUPPLIER ||--o{ SUPPLIER_BANK_ACCOUNT : has
  SUPPLIER ||--o{ CONTRACT_HEADER : "bound by"
  CONTRACT_HEADER ||--o{ CONTRACT_ITEM : contains
  CONTRACT_HEADER |o--o| DOCUMENT : "full text in"
  PURCHASE_ORDER_HEADER ||--|{ PURCHASE_ORDER_ITEM : contains
  MATERIAL ||--o{ PURCHASE_ORDER_ITEM : ordered
  CONTRACT_ITEM |o--o{ PURCHASE_ORDER_ITEM : "price source"
  PURCHASE_ORDER_ITEM ||--o{ GOODS_RECEIPT : "received via"
  PURCHASE_ORDER_ITEM ||--o{ INVOICE_ITEM : "invoiced via"
  INVOICE_HEADER ||--|{ INVOICE_ITEM : contains
  INVOICE_HEADER ||--o{ PAYMENT : "paid by"
  INVOICE_ITEM ||--o{ MATCH_RESULT : "evaluated in"
  MATCH_RUN ||--o{ MATCH_RESULT : produces
  INVOICE_HEADER ||--o{ EXCEPTION : raises
  INVOICE_HEADER ||--o{ DUPLICATE_CANDIDATE : "suspected in"
  INVOICE_HEADER ||--o| CASE : "investigated in"
  CASE ||--o{ CASE_FINDING : contains
  CASE ||--o{ ACTION_REQUEST : proposes
  DOCUMENT ||--|{ CHUNK : "split into"
```

### 10.3 Data-design decisions worth noting
- **Composite natural keys** for SAP-like objects (`po_number + item_no`) plus surrogate IDs where convenient, so the data reads as recognizably SAP to an SAP reviewer.
- **GR reversals are separate rows** (movement type 102) — never updates. This reflects how ERP systems keep history, and it is a classic source of matching bugs.
- **Invoices vs. credit memos** share one table (`doc_type`), as in RBKP.
- **Validity dating** (`valid_from/to`) on contracts, bank accounts and documents → enables "as-of" questions and the bank-change fraud check.
- **Curated SQL views** (`erp_v.*`) are the *only* surface the agent's DB role can see.
- **Embedding dimension** is fixed by the chosen model (pgvector indexes `vector` up to 2,000 dims and `halfvec` up to 4,000), so the model choice (Q3) must happen before the docs schema migration.

### 10.4 Synthetic data plan (Phase 2 preview)
- Scale: ~60 suppliers, ~400 materials, ~3,000 POs / ~9,000 PO items, ~8,000 GR lines, ~4,000 invoices over 18 months, 2 company codes. **[ASSUMPTION]**
- Supplier "personas" with different behavior (reliable / chronically late / price-creep / sloppy invoicer / one fraud-like bank change).
- **Seeded exceptions at realistic rates** (≈ 15–25 % of invoices with ≥ 1 exception), each recorded in a hidden `ground_truth_label` table used *only* by evaluation. Hard negatives included: e.g., same-reference credit memos and split deliveries that look like quantity variances but are legitimate.
- Deterministic random seed → reproducible dataset.

---

## 11. Agent responsibility matrix

### 11.1 Staged agent roadmap (challenge to the brief)

| Brief proposed | Our proposal | Reason |
|---|---|---|
| A. Orchestrator Agent | **Phase 4a:** deterministic graph (no LLM routing needed for "investigate invoice X"). **Phase 4b:** lightweight LLM router for free-text chat (fast, cheap model) | Routing "investigate" requests through an LLM wastes latency; free text does need it |
| B. ERP Data Analyst | **Yes** — core agent (tools: invoice, PO, GR, match, KPI) | Highest value |
| C. Document Intelligence | **Yes** — Phase 4b specialist (or a tool of the investigator in 4a) | Separate prompt with citation rules; isolated context keeps long passages away from analytics reasoning |
| D. Supplier Intelligence | **Tools first** (`get_supplier_performance`, `get_supplier_risk`) used by the ERP Analyst; promote to an agent only if eval shows a need | It is a set of queries, not a distinct reasoning skill |
| E. Business Process Agent | **Tools first** (`get_stage_lead_times`, `get_backlog_ageing`) — same logic | Same |
| F. Decision Support | **Synthesis node** with a strict output schema (not a free-roaming agent) | Its job is structured combination plus labeling — a single structured LLM call |
| G. Workflow Execution Agent | **Not an LLM agent.** Deterministic Action Service behind an approval interrupt; the LLM only drafts supplier messages | Writes must be deterministic, permissioned and idempotent |

Explicit **promotion criterion** for splitting a tool group into its own agent: tool-selection accuracy < 90 % or task success drops > 5 pp when the tool group is added to the shared agent, measured on the eval set.

### 11.2 Investigation graph (Phase 4a/5)

```mermaid
flowchart LR
  S((start)) --> L[load_case<br/>deterministic]
  L --> E[gather_evidence<br/>deterministic tools]
  E --> A{{investigator agent<br/>Claude + read-only tools}}
  A -->|tool calls| A
  A --> SYN[synthesize_finding<br/>strict schema: FACT/CALC/INTERP/REC]
  SYN --> GC[grounding_check<br/>deterministic]
  GC -->|fail ≤1 retry| A
  GC -->|pass| P[propose_action]
  P --> H[/human_approval<br/>interrupt — durable/]
  H -->|approved| X[execute_action<br/>Action Service, idempotent]
  H -->|rejected| R[record_rejection]
  X --> AU[audit + close] --> F((end))
  R --> F
```
Note from the LangGraph docs: on resume, the interrupted node **re-runs from the start**. So `human_approval` must contain no side effects before `interrupt()`, and execution lives in a separate node — exactly as designed above.

### 11.3 Responsibility matrix

| Component | Type | Responsibilities | Tools / inputs | Data access | Model **[ASSUMPTION]** | Output contract | Phase |
|---|---|---|---|---|---|---|---|
| Router | LLM (small) | Classify the free-text request → workflow (investigate / analytics / policy Q&A / report) | none (structured output) | none | Claude Haiku 5.5 | `RouteDecision` enum + extracted IDs | 4b |
| Investigator / ERP Data Analyst | LLM agent | Investigate exceptions, answer data questions, supplier and process analysis | `get_invoice`, `get_po`, `get_goods_receipts`, `get_match_result`, `find_duplicate_candidates`, `list_exceptions`, `compute_kpi`, `get_supplier_performance`, `get_supplier_risk`, `get_stage_lead_times` | read-only views via services | Claude Sonnet 5.5 | Evidence list + interim notes | 4a |
| Document Intelligence | LLM agent | Find and quote contract/policy passages; say "not found" when absent | `search_documents(query, doc_types, supplier_id, as_of)`, `get_contract_terms` | `docs` (read) | Claude Sonnet 5.5 (or Haiku if eval allows) | `PolicyEvidence[]` with citations | 4a tool → 4b agent |
| Decision Support | LLM node (single call) | Combine evidence into a labeled finding and recommendation with options, risks and € impact | state only | none | Claude Sonnet 5.5 | `CaseFinding` (strict schema) | 4a |
| Grounding Check | Deterministic | Every number in the finding exists in tool outputs; every policy claim has a valid citation ID | state | none | — | pass/fail + violations | 4a |
| Action Proposer | Deterministic | Map the recommendation → typed `ActionRequest`, check limits, set the approver role | state | `ops` (insert PENDING) | — | `ActionRequest` | 5 |
| Action Service | Deterministic | Execute approved actions idempotently; write the ERP simulation; audit | approved request | `eops_action` role | — | execution result | 5 |
| Message Drafter | LLM (single call) | Draft supplier inquiry / credit-memo request text from the finding | finding | none | Claude Haiku 5.5 | draft text (never sent automatically) | 5 |

**Tool design rules:** strict JSON schemas (`strict: true`, `additionalProperties: false`), enums for KPI names and exception codes, bounded result sizes (top-N + totals), every tool result carries a `source_ref` (table + key or chunk ID) that the grounding check uses, and every tool call is logged with its arguments.

### 11.4 Shared state (conceptual)
`InvestigationState`: `case_id`, `invoice_id`, `user {id, role, approval_limit}`, `messages`, `evidence[] {source_ref, payload}`, `citations[]`, `finding: CaseFinding | None`, `grounding: {passed, violations}`, `proposed_action: ActionRequest | None`, `approval: {status, approver, comment}`, `budget {tokens_used, tool_calls, max}`, `trace_id`.

---

## 12. Technology selection with justification

| Layer | Choice | Justification | Considered / rejected |
|---|---|---|---|
| Language/API | **Python 3.12, FastAPI, Pydantic v2** | Async, OpenAPI docs generated automatically, Pydantic validation shared by API and agent schemas | Django (heavier, ORM-centric) |
| DB access | **SQLAlchemy 2.0 (Core for analytics) + psycopg 3 + Alembic** | Mature, typed, migrations needed for an evolving schema. *New dependency — justified by migrations and connection pooling.* | Raw psycopg only (no migrations); SQLModel (thinner docs for complex cases) |
| Database | **PostgreSQL 17 + pgvector (0.8.x)** | One DB for relational data, vectors (HNSW, iterative index scans for filtered search since 0.8.0), FTS for hybrid search, checkpoints and audit | Separate vector DB — overkill at <100k chunks |
| LLM | **Claude API** via the official `anthropic` SDK; Sonnet 5.5 for reasoning, Haiku 5.5 for routing/drafting | Strict tool use guarantees schema-valid tool inputs; prompt caching lowers cost for static prompts/tools; strong tool-use reliability | Multi-provider abstraction frameworks (abstraction cost > benefit now; a thin internal interface is enough) |
| Orchestration | **LangGraph** | Durable checkpoints (Postgres checkpointer), `interrupt()`/`Command(resume=…)` for HITL, explicit graph = auditable control flow, subgraphs for later specialists | CrewAI/AutoGen (less control over deterministic steps); a plain SDK loop (fine for 4a, but we would rebuild durable HITL ourselves) |
| Embeddings | **Open decision (Q3):** Voyage AI API vs. a local open-source model | Anthropic doesn't offer an embedding model. The choice depends on document language and budget; decided by a small retrieval eval in week 4 | — |
| RAG | Hybrid: pgvector HNSW + Postgres FTS, merged by **Reciprocal Rank Fusion**; structure-aware chunking (by contract section) | Contracts are full of exact terms (clause numbers, "Incoterms", article numbers) where keyword search beats vectors; RRF is simple and robust | Pure vector search; a reranker model (add later only if eval shows a need) |
| Data generation | **Faker + NumPy + Pandas** (offline only) | Realistic names/dates; distributions for delays and price creep | — |
| Frontend | **React + TypeScript + Vite + Tailwind + Recharts**; TanStack Query for server state | Matches your skills; Recharts is enough for KPI charts | Next.js (SSR not needed for an internal tool) |
| Auth | JWT (FastAPI security utilities), demo users per role | Enough to demonstrate RBAC/SoD | Keycloak/Auth0 (later, if deployed publicly) |
| Observability | **Structured JSON logging (structlog) + LangSmith tracing** (free tier) + `ops.agent_run` metrics table | LangSmith integrates natively with LangGraph; our own metrics table keeps eval independent of the vendor | Langfuse self-hosted (good alternative — Q10) |
| Evaluation | **In-repo pytest-based eval harness** + datasets in `evaluation/`; LLM-as-judge only where needed (citation support), calibrated against a manual sample | Reproducible, CI-runnable (mocked), vendor-neutral | Eval only inside a SaaS tool |
| Quality | ruff, mypy, pytest, coverage, gitleaks, pre-commit | Standard | — |
| Infra | Docker Compose (`pgvector/pgvector:pg17`, api, frontend); GitHub Actions CI | Reproducible one-command setup | Kubernetes (unnecessary) |
| Background work | **FastAPI + LangGraph durable runs; no Celery/Redis in v1** | Investigation runs are seconds long; checkpoints provide durability | Celery + Redis — add only if batch workloads need it |
| MCP | **Python MCP SDK**, read-only tool server (week 7, "Could") | Demonstrates the standard without putting it on the critical path | Internal MCP transport |

**SAP integration path (documentation deliverable, not code in v1):** the `ErpAdapter` interface mirrors standard S/4HANA Cloud APIs from the SAP Business Accelerator Hub — Purchase Order (`API_PURCHASEORDER_PROCESS_SRV` / OData V4 successor), Material Documents (`API_MATERIAL_DOCUMENT_SRV`, goods receipts), Supplier Invoice (`API_SUPPLIERINVOICE_PROCESS_SRV`) and Business Partner (`API_BUSINESS_PARTNER`). **[ASSUMPTION — exact service names/versions must be verified on api.sap.com before any adapter is built; SAP is moving several APIs to OData V4.]** We'll produce a field-mapping table (our columns ↔ SAP fields) in `DATABASE_SCHEMA.md`.

---

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

---

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

---

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

## 16. Assumptions (to confirm or correct)

| ID | Assumption |
|---|---|
| A1 | The product is a **portfolio-grade simulation**; no real company data and no live SAP connection in v1. |
| A2 | Single tenant; 2 company codes; EUR primary currency plus one foreign currency for test cases. |
| A3 | Invoices arrive as **structured records** (as after OCR/e-invoicing capture). OCR is out of scope. (Note: e-invoicing via XRechnung/ZUGFeRD is becoming mandatory in German B2B — a structured import of such files could be a strong "Could" feature later.) |
| A4 | Documents (contracts/policies) are authored by us, in **English**. |
| A5 | You have ~20–25 h/week for 8 weeks. |
| A6 | LLM budget of roughly €20–50 for the whole project including evals. |
| A7 | Local Docker deployment is sufficient; public cloud deployment is optional. |
| A8 | Tolerance limits, approval limits and policy rules are invented but plausible, and documented in the policy documents themselves (so RAG and the deterministic rules agree). |
| A9 | The public GitHub repo will contain the synthetic data generator, not large generated data files. |

## 17. Open questions (need your answer)

| ID | Question | Why it matters |
|---|---|---|
| Q1 | How many hours per week can you realistically invest, and is there a hard deadline (semester, application date)? | Roadmap realism / scope cuts |
| Q2 | Should documents be English only, or also **German** (e.g., German contracts)? | Embedding model choice; demo realism for German employers |
| Q3 | Embeddings: an external API (e.g., Voyage AI — another API key and cost) or a **local open-source model** (free, runs in Docker, slower and larger images)? | The docs schema depends on the vector dimension |
| Q4 | Do you have access to an SAP system via HFU (e.g., SAP University Competence Center / S/4HANA with the Global Bike dataset)? | We could align the synthetic data with a model you already know, and mention it credibly |
| Q5 | What monthly LLM API budget is acceptable? | Model choices, eval size |
| Q6 | Deployment target: local only, or a public demo URL? | Auth hardening, hosting cost |
| Q7 | Do you agree with **not** making Supplier Intelligence, Business Process and Workflow Execution separate LLM agents initially (§11.1)? | The largest deviation from your brief |
| Q8 | Is text-to-SQL (constrained, read-only views, AST-validated) something you specifically want to showcase? If not, we drop it entirely. | Security surface vs. portfolio value |
| Q9 | Tolerance semantics: raise the exception when **either** the % or the absolute limit is breached (strict), or only when **both** are? | Matching behavior; must match the policy document |
| Q10 | Tracing: LangSmith (hosted, easiest with LangGraph) or Langfuse (open-source, self-hosted in Docker)? | Vendor dependence vs. setup effort |

---

## 18. Decisions requested for approval

Please approve, reject or modify each:

1. **D1** — Deterministic matching / duplicate / KPI core; LLM explains only (ADR-001).
2. **D2** — Staged agents: Investigator + Decision Support node + deterministic workflow first; router and Document specialist in week 6; other agents only on evidence (ADR-002, §11.1).
3. **D3** — Agents have no write tools; HITL interrupt + Action Service (ADR-003).
4. **D4** — Typed tool catalog; text-to-SQL deferred / optional (ADR-004).
5. **D5** — LangGraph + official `anthropic` SDK (ADR-005).
6. **D6** — PostgreSQL-only data platform with pgvector + FTS hybrid retrieval (ADR-006).
7. **D7** — SAP-aligned model + adapter interface; no live SAP integration in v1 (ADR-007).
8. **D8** — MCP as an optional outer interface in week 7 (ADR-009).
9. **D9** — The 8-week roadmap and gates in §13.

After approval, the next step is **Week 1**: repo scaffold, Docker/Postgres, CI, and splitting this package into the 9 maintained project documents.

---

### Sources consulted
- LangGraph — Interrupts (HITL, checkpointer requirement, node re-execution on resume): https://docs.langchain.com/oss/python/langgraph/interrupts
- LangChain — Multi-agent patterns and when a single agent suffices: https://docs.langchain.com/oss/python/langchain/multi-agent
- LangGraph — Workflows and agents: https://docs.langchain.com/oss/python/langgraph/workflows-agents
- Claude API — Strict tool use: https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use
- Claude API — Structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- pgvector README (HNSW vs IVFFlat, iterative index scans ≥ 0.8.0, hybrid search with FTS/RRF, dimension limits): https://github.com/pgvector/pgvector/blob/master/README.md
- SAP Help — API for Supplier Invoice: https://help.sap.com/docs/SAP_S4HANA_CLOUD/0864cb07010642b3bde45a20de4975bc/8ddf1d448ce74a799390a1706d90ca3d.html
- SAP Help — Tolerance Limits for Invoice Postings: https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/b7eb2f9e70ab4c88abbff8b34a409b26/ec236b54f94c8f4ce10000000a4450e5.html
- SAP Learning — Entering Invoices with Variances: https://learning.sap.com/courses/invoice-verification-in-sap-s-4hana/entering-invoices-with-variances-1
- SAP Community — Duplicate Invoice Check: https://community.sap.com/t5/enterprise-resource-planning-blog-posts-by-members/duplicate-invoice-check-part-1/ba-p/13231296
- Crunchy Data — Hybrid search with Postgres and pgvector: https://www.crunchydata.com/blog/hybrid-vector-search
