"""Database table definitions (SQLAlchemy Core) - the single source of truth.

Alembic migrations are generated from this metadata, reviewed and committed;
``tests/test_schema_drift.py`` fails if a migration and this file disagree.

Schemas (see docs/DATABASE_SCHEMA.md):
  erp  - simulated SAP-aligned source system. SAP analogue in each table comment.
  iam  - users and roles.
  ops  - EnterpriseOps configuration and (Task 3+) matching results.
  eval - ground-truth labels for evaluation. NEVER readable by the agent role.

Money conventions (ADR-012): amounts NUMERIC(15,2), unit prices NUMERIC(15,4),
quantities NUMERIC(13,3). No floats anywhere.
"""

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

# Deterministic constraint names keep autogenerate diffs and migrations stable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

# Schemas owned by our migrations (public only holds alembic_version).
MANAGED_SCHEMAS = frozenset({"erp", "ops", "docs", "audit", "iam", "eval", "agent"})


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Alembic filter: compare only objects inside MANAGED_SCHEMAS."""
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    return True


MONEY = Numeric(15, 2)
PRICE = Numeric(15, 4)
QTY = Numeric(13, 3)
PCT = Numeric(7, 3)

# --------------------------------------------------------------------------- erp

company_code = Table(
    "company_code",
    metadata,
    Column("company_code", CHAR(4), primary_key=True),
    Column("name", String(80), nullable=False),
    Column("country", CHAR(2), nullable=False),
    Column("currency", CHAR(3), nullable=False),
    schema="erp",
    comment="Legal entity (SAP T001)",
)

plant = Table(
    "plant",
    metadata,
    Column("plant_id", CHAR(4), primary_key=True),
    Column("company_code", CHAR(4), ForeignKey("erp.company_code.company_code"), nullable=False),
    Column("name", String(80), nullable=False),
    Column("city", String(60), nullable=False),
    schema="erp",
    comment="Plant / receiving location (SAP T001W)",
)

payment_terms = Table(
    "payment_terms",
    metadata,
    Column("terms_code", CHAR(4), primary_key=True),
    Column("description", String(80), nullable=False),
    Column("net_days", Integer, nullable=False),
    Column("discount_days", Integer, nullable=True),
    Column("discount_pct", PCT, nullable=True),
    CheckConstraint("net_days > 0", name="net_days_positive"),
    CheckConstraint(
        "(discount_days IS NULL AND discount_pct IS NULL) OR "
        "(discount_days > 0 AND discount_days <= net_days AND discount_pct > 0)",
        name="discount_consistent",
    ),
    schema="erp",
    comment="Payment terms (SAP T052)",
)

supplier = Table(
    "supplier",
    metadata,
    Column("supplier_id", String(10), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("country", CHAR(2), nullable=False),
    Column("city", String(60), nullable=False),
    Column("vat_id", String(20), nullable=False),
    Column("terms_code", CHAR(4), ForeignKey("erp.payment_terms.terms_code"), nullable=False),
    Column("created_on", Date, nullable=False),
    Column("is_blocked", Boolean, nullable=False, server_default="false"),
    Index(None, "vat_id"),
    schema="erp",
    comment="Supplier master (SAP LFA1 / Business Partner)",
)

supplier_bank_account = Table(
    "supplier_bank_account",
    metadata,
    Column("bank_account_id", Integer, primary_key=True, autoincrement=True),
    Column("supplier_id", String(10), ForeignKey("erp.supplier.supplier_id"), nullable=False),
    Column("iban_masked", String(42), nullable=False),
    Column("iban_hash", CHAR(64), nullable=False, comment="SHA-256 of the IBAN"),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date, nullable=True),
    Column("changed_by", String(40), nullable=False),
    UniqueConstraint("supplier_id", "valid_from"),
    CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="validity_order"),
    schema="erp",
    comment="Supplier bank details with validity history (SAP LFBK / BP bank)",
)

material = Table(
    "material",
    metadata,
    Column("material_id", String(18), primary_key=True),
    Column("description", String(120), nullable=False),
    Column("material_group", String(12), nullable=False),
    Column("base_uom", String(3), nullable=False),
    Column("standard_price", PRICE, nullable=False),
    CheckConstraint("standard_price > 0", name="standard_price_positive"),
    Index(None, "material_group"),
    schema="erp",
    comment="Material master (SAP MARA/MBEW)",
)

contract_header = Table(
    "contract_header",
    metadata,
    Column("contract_id", String(10), primary_key=True),
    Column("supplier_id", String(10), ForeignKey("erp.supplier.supplier_id"), nullable=False),
    Column("company_code", CHAR(4), ForeignKey("erp.company_code.company_code"), nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date, nullable=False),
    Column("currency", CHAR(3), nullable=False),
    Column("terms_code", CHAR(4), ForeignKey("erp.payment_terms.terms_code"), nullable=False),
    Column("document_ref", String(64), nullable=True, comment="Link to the RAG document (Task 4)"),
    CheckConstraint("valid_to > valid_from", name="validity_order"),
    schema="erp",
    comment="Outline agreement / contract (SAP EKKO, doc. category K)",
)

contract_item = Table(
    "contract_item",
    metadata,
    Column(
        "contract_id", String(10), ForeignKey("erp.contract_header.contract_id"), primary_key=True
    ),
    Column("item_no", Integer, primary_key=True),
    Column("material_id", String(18), ForeignKey("erp.material.material_id"), nullable=False),
    Column("agreed_price", PRICE, nullable=False),
    CheckConstraint("agreed_price > 0", name="agreed_price_positive"),
    UniqueConstraint("contract_id", "material_id"),
    schema="erp",
    comment="Contract item with agreed price (SAP EKPO for contracts)",
)

purchase_order_header = Table(
    "purchase_order_header",
    metadata,
    Column("po_number", String(10), primary_key=True),
    Column("supplier_id", String(10), ForeignKey("erp.supplier.supplier_id"), nullable=False),
    Column("company_code", CHAR(4), ForeignKey("erp.company_code.company_code"), nullable=False),
    Column("purch_org", CHAR(4), nullable=False),
    Column("doc_date", Date, nullable=False),
    Column("created_by", String(20), nullable=False),
    Column("currency", CHAR(3), nullable=False),
    Column("terms_code", CHAR(4), ForeignKey("erp.payment_terms.terms_code"), nullable=False),
    Index(None, "supplier_id"),
    Index(None, "doc_date"),
    schema="erp",
    comment="Purchase order header (SAP EKKO)",
)

purchase_order_item = Table(
    "purchase_order_item",
    metadata,
    Column(
        "po_number",
        String(10),
        ForeignKey("erp.purchase_order_header.po_number"),
        primary_key=True,
    ),
    Column("item_no", Integer, primary_key=True),
    Column("material_id", String(18), ForeignKey("erp.material.material_id"), nullable=False),
    Column("plant_id", CHAR(4), ForeignKey("erp.plant.plant_id"), nullable=False),
    Column("quantity", QTY, nullable=False),
    Column("uom", String(3), nullable=False),
    Column("net_price", PRICE, nullable=False, comment="Price per 1 unit of uom"),
    Column("delivery_date", Date, nullable=False, comment="Promised delivery date (SAP EKET)"),
    Column("gr_based_iv", Boolean, nullable=False, server_default="true"),
    Column("contract_id", String(10), nullable=True),
    Column("contract_item_no", Integer, nullable=True),
    Column("tax_code", CHAR(2), nullable=False),
    Column("deletion_flag", Boolean, nullable=False, server_default="false"),
    CheckConstraint("quantity > 0", name="quantity_positive"),
    CheckConstraint("net_price > 0", name="net_price_positive"),
    CheckConstraint(
        "(contract_id IS NULL) = (contract_item_no IS NULL)", name="contract_ref_complete"
    ),
    ForeignKeyConstraint(
        ["contract_id", "contract_item_no"],
        ["erp.contract_item.contract_id", "erp.contract_item.item_no"],
    ),
    Index(None, "material_id"),
    schema="erp",
    comment="Purchase order item (SAP EKPO)",
)

goods_receipt = Table(
    "goods_receipt",
    metadata,
    Column("mat_doc", String(10), primary_key=True),
    Column("mat_doc_year", Integer, primary_key=True),
    Column("line_no", Integer, primary_key=True),
    Column("po_number", String(10), nullable=False),
    Column("po_item_no", Integer, nullable=False),
    Column("movement_type", CHAR(3), nullable=False, comment="101 receipt, 102 reversal"),
    Column("quantity", QTY, nullable=False, comment="Always positive; 102 reduces the receipt"),
    Column("posting_date", Date, nullable=False),
    Column("plant_id", CHAR(4), ForeignKey("erp.plant.plant_id"), nullable=False),
    Column("ref_mat_doc", String(10), nullable=True),
    Column("ref_mat_doc_year", Integer, nullable=True),
    Column("ref_line_no", Integer, nullable=True),
    CheckConstraint("quantity > 0", name="quantity_positive"),
    CheckConstraint("movement_type IN ('101', '102')", name="movement_type_valid"),
    CheckConstraint(
        "(movement_type = '101' AND ref_mat_doc IS NULL) OR "
        "(movement_type = '102' AND ref_mat_doc IS NOT NULL)",
        name="reversal_has_reference",
    ),
    ForeignKeyConstraint(
        ["po_number", "po_item_no"],
        ["erp.purchase_order_item.po_number", "erp.purchase_order_item.item_no"],
    ),
    ForeignKeyConstraint(
        ["ref_mat_doc", "ref_mat_doc_year", "ref_line_no"],
        [
            "erp.goods_receipt.mat_doc",
            "erp.goods_receipt.mat_doc_year",
            "erp.goods_receipt.line_no",
        ],
        name="fk_goods_receipt_reversal_ref",
    ),
    Index(None, "po_number", "po_item_no"),
    schema="erp",
    comment="Goods movement for a PO item (SAP MATDOC/MSEG); reversals are separate rows",
)

invoice_header = Table(
    "invoice_header",
    metadata,
    Column("invoice_id", String(10), primary_key=True),
    Column("doc_type", String(12), nullable=False),
    Column("supplier_id", String(10), ForeignKey("erp.supplier.supplier_id"), nullable=False),
    Column("company_code", CHAR(4), ForeignKey("erp.company_code.company_code"), nullable=False),
    Column("supplier_reference", String(20), nullable=False, comment="Supplier's invoice number"),
    Column("invoice_date", Date, nullable=False),
    Column("received_date", Date, nullable=False),
    Column("posting_date", Date, nullable=True),
    Column("currency", CHAR(3), nullable=False),
    Column("net_amount", MONEY, nullable=False),
    Column("tax_amount", MONEY, nullable=False),
    Column("gross_amount", MONEY, nullable=False),
    Column("terms_code", CHAR(4), ForeignKey("erp.payment_terms.terms_code"), nullable=False),
    Column("status", String(10), nullable=False),
    Column("payment_block", CHAR(1), nullable=True, comment="Set by matching (Task 3)"),
    Column(
        "reference_invoice_id",
        String(10),
        ForeignKey("erp.invoice_header.invoice_id"),
        nullable=True,
        comment="Credit memo -> original invoice",
    ),
    CheckConstraint("doc_type IN ('INVOICE', 'CREDIT_MEMO')", name="doc_type_valid"),
    CheckConstraint("status IN ('RECEIVED', 'PAID')", name="status_valid"),
    CheckConstraint("net_amount >= 0 AND tax_amount >= 0", name="amounts_non_negative"),
    CheckConstraint("gross_amount = net_amount + tax_amount", name="gross_is_net_plus_tax"),
    CheckConstraint("received_date >= invoice_date", name="received_after_invoice_date"),
    CheckConstraint(
        "posting_date IS NULL OR posting_date >= received_date", name="posted_after_receipt"
    ),
    Index(None, "supplier_id", "supplier_reference"),
    Index(None, "invoice_date"),
    schema="erp",
    comment="Supplier invoice / credit memo header (SAP RBKP)",
)

invoice_item = Table(
    "invoice_item",
    metadata,
    Column("invoice_id", String(10), ForeignKey("erp.invoice_header.invoice_id"), primary_key=True),
    Column("item_no", Integer, primary_key=True),
    Column("po_number", String(10), nullable=True),
    Column("po_item_no", Integer, nullable=True),
    Column("material_id", String(18), ForeignKey("erp.material.material_id"), nullable=True),
    Column("description", String(120), nullable=False),
    Column("quantity", QTY, nullable=False),
    Column("unit_price", PRICE, nullable=False),
    Column("net_amount", MONEY, nullable=False),
    Column("tax_code", CHAR(2), nullable=False),
    CheckConstraint("quantity > 0", name="quantity_positive"),
    CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
    CheckConstraint("(po_number IS NULL) = (po_item_no IS NULL)", name="po_ref_complete"),
    ForeignKeyConstraint(
        ["po_number", "po_item_no"],
        ["erp.purchase_order_item.po_number", "erp.purchase_order_item.item_no"],
    ),
    Index(None, "po_number", "po_item_no"),
    schema="erp",
    comment="Supplier invoice item (SAP RSEG)",
)

payment = Table(
    "payment",
    metadata,
    Column("payment_id", String(10), primary_key=True),
    Column("invoice_id", String(10), ForeignKey("erp.invoice_header.invoice_id"), nullable=False),
    Column("payment_date", Date, nullable=False),
    Column("amount", MONEY, nullable=False),
    Column("discount_taken", MONEY, nullable=False, server_default="0"),
    Column("currency", CHAR(3), nullable=False),
    CheckConstraint("amount > 0 AND discount_taken >= 0", name="amounts_valid"),
    Index(None, "invoice_id"),
    schema="erp",
    comment="Outgoing payment cleared against an invoice (SAP payment run / BSAK)",
)

inventory_level = Table(
    "inventory_level",
    metadata,
    Column("material_id", String(18), ForeignKey("erp.material.material_id"), primary_key=True),
    Column("plant_id", CHAR(4), ForeignKey("erp.plant.plant_id"), primary_key=True),
    Column("as_of", Date, primary_key=True),
    Column("quantity", QTY, nullable=False),
    CheckConstraint("quantity >= 0", name="quantity_non_negative"),
    schema="erp",
    comment="Stock snapshot (SAP MARD); minimal - no v1 use case needs more",
)

# --------------------------------------------------------------------------- iam

role = Table(
    "role",
    metadata,
    Column("role_code", String(24), primary_key=True),
    Column("description", String(120), nullable=False),
    Column("approval_limit_eur", MONEY, nullable=True, comment="NULL = may not approve"),
    schema="iam",
)

app_user = Table(
    "app_user",
    metadata,
    Column("user_id", String(20), primary_key=True),
    Column("display_name", String(80), nullable=False),
    Column("email", String(120), nullable=False, unique=True),
    Column("role_code", String(24), ForeignKey("iam.role.role_code"), nullable=False),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    schema="iam",
)

# --------------------------------------------------------------------------- ops

tolerance_rule = Table(
    "tolerance_rule",
    metadata,
    Column(
        "company_code",
        CHAR(4),
        ForeignKey("erp.company_code.company_code"),
        primary_key=True,
    ),
    Column("tolerance_key", CHAR(2), primary_key=True, comment="PP price, DQ quantity, BD small"),
    Column("description", String(120), nullable=False),
    Column("lower_abs", MONEY, nullable=True),
    Column("upper_abs", MONEY, nullable=True),
    Column("lower_pct", PCT, nullable=True),
    Column("upper_pct", PCT, nullable=True),
    Column("policy_ref", String(120), nullable=False, comment="Section of the AP Tolerance Policy"),
    schema="ops",
    comment="Invoice tolerance limits (SAP OMR6). Rule semantics: ADR-016",
)

# ------------------------------------------------------------ ops: matching (Task 3)

match_run = Table(
    "match_run",
    metadata,
    Column("run_id", Integer, primary_key=True, autoincrement=True),
    Column("engine_version", String(20), nullable=False),
    Column("params", JSONB, nullable=False, comment="Tolerances + duplicate settings used"),
    Column("params_hash", CHAR(64), nullable=False),
    Column("status", String(10), nullable=False),
    Column("triggered_by", String(40), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("invoice_count", Integer, nullable=False, server_default="0"),
    Column("exception_count", Integer, nullable=False, server_default="0"),
    CheckConstraint("status IN ('RUNNING', 'COMPLETED', 'FAILED')", name="status_valid"),
    schema="ops",
    comment="One deterministic matching run (versioned, never overwritten)",
)

invoice_result = Table(
    "invoice_result",
    metadata,
    Column("run_id", Integer, ForeignKey("ops.match_run.run_id"), primary_key=True),
    Column("invoice_id", String(10), ForeignKey("erp.invoice_header.invoice_id"), primary_key=True),
    Column("status", String(20), nullable=False),
    Column("blocks_payment", Boolean, nullable=False),
    Column("exception_count", Integer, nullable=False),
    Column("amount_at_risk", MONEY, nullable=False),
    Column("currency", CHAR(3), nullable=False),
    CheckConstraint(
        "status IN ('MATCHED', 'WITHIN_TOLERANCE', 'BLOCKED', 'FLAGGED', 'NOT_APPLICABLE')",
        name="status_valid",
    ),
    Index(None, "invoice_id"),
    schema="ops",
    comment="Invoice-level outcome of a run",
)

line_result = Table(
    "line_result",
    metadata,
    Column("run_id", Integer, ForeignKey("ops.match_run.run_id"), primary_key=True),
    Column("invoice_id", String(10), primary_key=True),
    Column("item_no", Integer, primary_key=True),
    Column("po_number", String(10), nullable=True),
    Column("po_item_no", Integer, nullable=True),
    Column("po_qty", QTY, nullable=True),
    Column("net_received_qty", QTY, nullable=True),
    Column("previously_invoiced_qty", QTY, nullable=True),
    Column("invoiced_qty", QTY, nullable=False),
    Column("po_price", PRICE, nullable=True),
    Column("invoice_price", PRICE, nullable=False),
    Column("price_variance_amount", MONEY, nullable=True),
    Column("price_variance_pct", PCT, nullable=True),
    Column("price_outcome", String(20), nullable=True),
    Column("qty_outcome", String(20), nullable=True),
    ForeignKeyConstraint(
        ["invoice_id", "item_no"],
        ["erp.invoice_item.invoice_id", "erp.invoice_item.item_no"],
    ),
    schema="ops",
    comment="Three-way match detail per invoice line",
)

exception = Table(
    "exception",
    metadata,
    Column("exception_id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("ops.match_run.run_id"), nullable=False),
    Column("invoice_id", String(10), ForeignKey("erp.invoice_header.invoice_id"), nullable=False),
    Column("item_no", Integer, nullable=True, comment="NULL = invoice-level exception"),
    Column("code", String(40), nullable=False),
    Column("severity", String(10), nullable=False),
    Column("blocks_payment", Boolean, nullable=False),
    Column("amount_at_risk", MONEY, nullable=False),
    Column("currency", CHAR(3), nullable=False),
    Column("details", JSONB, nullable=False, server_default="{}"),
    Column("status", String(12), nullable=False, server_default="OPEN"),
    CheckConstraint("severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="severity_valid"),
    Index(None, "run_id", "code"),
    Index(None, "invoice_id"),
    schema="ops",
    comment="Exception found by the deterministic engine (taxonomy: PROJECT_REQUIREMENTS 8.3)",
)

duplicate_candidate = Table(
    "duplicate_candidate",
    metadata,
    Column("run_id", Integer, ForeignKey("ops.match_run.run_id"), primary_key=True),
    Column("invoice_id", String(10), ForeignKey("erp.invoice_header.invoice_id"), primary_key=True),
    Column(
        "candidate_invoice_id",
        String(10),
        ForeignKey("erp.invoice_header.invoice_id"),
        primary_key=True,
        comment="The earlier invoice this one may duplicate",
    ),
    Column("score", Numeric(4, 3), nullable=False),
    Column("is_flagged", Boolean, nullable=False),
    Column("features", JSONB, nullable=False),
    schema="ops",
    comment="Scored duplicate pairs (flagged at or above the configured threshold)",
)

# --------------------------------------------------------------------------- eval

dataset_run = Table(
    "dataset_run",
    metadata,
    Column("run_id", Integer, primary_key=True, autoincrement=True),
    Column("seed", Integer, nullable=False),
    Column("profile", String(20), nullable=False),
    Column("generator_version", String(20), nullable=False),
    Column("generated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("row_counts", JSONB, nullable=False),
    Column("content_hash", CHAR(64), nullable=False),
    schema="eval",
    comment="Provenance of the loaded synthetic dataset",
)

supplier_persona = Table(
    "supplier_persona",
    metadata,
    Column("supplier_id", String(10), ForeignKey("erp.supplier.supplier_id"), primary_key=True),
    Column("persona", String(20), nullable=False),
    schema="eval",
    comment="Hidden behavior profile used to generate the supplier's data",
)

ground_truth_label = Table(
    "ground_truth_label",
    metadata,
    Column("label_id", Integer, primary_key=True, autoincrement=True),
    Column("invoice_id", String(10), ForeignKey("erp.invoice_header.invoice_id"), nullable=False),
    Column("item_no", Integer, nullable=True, comment="NULL = invoice-level label"),
    Column("label_code", String(40), nullable=False),
    Column("is_hard_negative", Boolean, nullable=False),
    Column("details", JSONB, nullable=False, server_default="{}"),
    Index(None, "invoice_id"),
    schema="eval",
    comment="Expected exception (or deliberate look-alike) per invoice/line",
)
