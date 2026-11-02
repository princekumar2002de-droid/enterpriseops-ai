"""Static reference data for the fictional company.

"Talwerk Pumpen GmbH" is invented. Any resemblance to a real company is coincidental.
All values here are deliberately plausible and are mirrored in the policy
documents written in Task 4 (tolerances, payment terms, approval limits).
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from data_generation.model import Row

COMPANY_CODES: list[Row] = [
    {"company_code": "DE01", "name": "Talwerk Pumpen GmbH", "country": "DE", "currency": "EUR"},
    {"company_code": "US01", "name": "Talwerk Pumps Inc.", "country": "US", "currency": "USD"},
]

PLANTS: list[Row] = [
    {"plant_id": "DE11", "company_code": "DE01", "name": "Pump assembly", "city": "Freiburg"},
    {"plant_id": "DE12", "company_code": "DE01", "name": "Motor & controls", "city": "Stuttgart"},
    {"plant_id": "US11", "company_code": "US01", "name": "Service center", "city": "Charlotte"},
]
PLANTS_BY_COMPANY = {"DE01": ["DE11", "DE12"], "US01": ["US11"]}
PURCH_ORG = {"DE01": "DE10", "US01": "US10"}

# terms_code, description, net_days, discount_days, discount_pct
PAYMENT_TERMS: list[Row] = [
    {
        "terms_code": "Z030",
        "description": "Net 30 days",
        "net_days": 30,
        "discount_days": None,
        "discount_pct": None,
    },
    {
        "terms_code": "Z060",
        "description": "Net 60 days",
        "net_days": 60,
        "discount_days": None,
        "discount_pct": None,
    },
    {
        "terms_code": "Z214",
        "description": "2% within 14 days, net 30",
        "net_days": 30,
        "discount_days": 14,
        "discount_pct": Decimal("2.000"),
    },
    {
        "terms_code": "Z310",
        "description": "3% within 10 days, net 45",
        "net_days": 45,
        "discount_days": 10,
        "discount_pct": Decimal("3.000"),
    },
]
TERMS_BY_CODE: dict[str, Row] = {t["terms_code"]: t for t in PAYMENT_TERMS}

# company -> (tax code, rate). Invoice tax is computed on the header net amount.
TAX = {"DE01": ("V1", Decimal("0.19")), "US01": ("U1", Decimal("0.07"))}

# ADR-016: a variance is out of tolerance if EITHER the % OR the absolute limit is
# exceeded. BD (small difference) is checked first: a line whose total price
# difference is <= BD upper_abs is accepted regardless of the percentage.
TOLERANCE_RULES: list[Row] = [
    {
        "tolerance_key": "PP",
        "description": "Price variance per invoice line",
        "lower_abs": Decimal("500.00"),
        "upper_abs": Decimal("100.00"),
        "lower_pct": Decimal("10.000"),
        "upper_pct": Decimal("2.000"),
        "policy_ref": "AP Tolerance Policy, section 3.1",
    },
    {
        "tolerance_key": "DQ",
        "description": "Quantity variance: invoiced > received",
        "lower_abs": None,
        "upper_abs": Decimal("0.00"),
        "lower_pct": None,
        "upper_pct": Decimal("0.000"),
        "policy_ref": "AP Tolerance Policy, section 3.2",
    },
    {
        "tolerance_key": "BD",
        "description": "Small difference, accepted automatically",
        "lower_abs": Decimal("5.00"),
        "upper_abs": Decimal("5.00"),
        "lower_pct": None,
        "upper_pct": None,
        "policy_ref": "AP Tolerance Policy, section 3.3",
    },
]

# (role_code, how many users)
USERS = [
    ("AP_CLERK", 2),
    ("AP_MANAGER", 1),
    ("FINANCE_MANAGER", 1),
    ("BUYER", 4),
    ("PROCUREMENT_MANAGER", 1),
    ("FINANCE_VIEWER", 1),
    ("AUDITOR", 1),
    ("ADMIN", 1),
]
EMAIL_DOMAIN = "talwerk.example"  # reserved .example TLD - never a real mailbox


class Persona(StrEnum):
    RELIABLE = "reliable"
    LATE = "chronically_late"
    PRICE_CREEP = "price_creep"
    SLOPPY = "sloppy_invoicer"
    FRAUD_SIGNAL = "fraud_signal"
    DUPLICATE_MASTER = "duplicate_master"  # second master record of a sloppy supplier


# Share of suppliers per persona (FRAUD_SIGNAL is always exactly one supplier).
PERSONA_SHARES = [
    (Persona.LATE, 0.15),
    (Persona.PRICE_CREEP, 0.10),
    (Persona.SLOPPY, 0.15),
]

# Delivery behavior: (probability on time, late-days range when late)
DELIVERY = {
    Persona.RELIABLE: (0.88, (1, 5)),
    Persona.LATE: (0.40, (3, 25)),
    Persona.PRICE_CREEP: (0.78, (1, 8)),
    Persona.SLOPPY: (0.75, (1, 8)),
    Persona.FRAUD_SIGNAL: (0.80, (1, 6)),
}


@dataclass(frozen=True)
class MaterialGroup:
    code: str
    nouns: tuple[str, ...]
    variants: tuple[str, ...]
    sizes: tuple[str, ...]
    uom: str
    price_range: tuple[float, float]
    lead_days: tuple[int, int]


MATERIAL_GROUPS = [
    MaterialGroup(
        "CASTINGS",
        ("Pump housing", "Impeller casting", "Bearing bracket", "Volute casing"),
        ("EN-GJL-250", "EN-GJS-400", "1.4408"),
        ("DN25", "DN32", "DN40", "DN50", "DN65", "DN80", "DN100"),
        "PC",
        (40, 900),
        (25, 45),
    ),
    MaterialGroup(
        "SEALS",
        ("Mechanical seal", "O-ring", "Flat gasket", "Shaft seal"),
        ("EPDM", "FKM", "NBR", "PTFE"),
        ("18mm", "24mm", "28mm", "32mm", "38mm", "45mm"),
        "PC",
        (0.4, 180),
        (7, 20),
    ),
    MaterialGroup(
        "MOTORS",
        ("IE3 motor", "IE4 motor", "Frequency converter"),
        ("0.37kW", "0.75kW", "1.5kW", "2.2kW", "4kW", "7.5kW", "15kW"),
        ("2-pole", "4-pole", "6-pole"),
        "PC",
        (180, 3200),
        (20, 40),
    ),
    MaterialGroup(
        "BEARINGS",
        ("Ball bearing", "Cylindrical roller bearing", "Sleeve bearing"),
        ("6204", "6205", "6306", "6308", "NU210", "22210"),
        ("C3", "2RS", "ZZ"),
        "PC",
        (6, 220),
        (10, 25),
    ),
    MaterialGroup(
        "FASTENERS",
        ("Hex bolt", "Socket head screw", "Washer", "Hex nut"),
        ("M6", "M8", "M10", "M12", "M16", "M20"),
        ("A2-70", "8.8", "A4-80"),
        "PC",
        (0.03, 1.5),
        (5, 12),
    ),
    MaterialGroup(
        "ELECTRONICS",
        ("Pressure sensor", "Flow sensor", "Control board", "Cable harness"),
        ("4-20mA", "0-10V", "Modbus", "IO-Link"),
        ("Rev A", "Rev B", "Rev C"),
        "PC",
        (15, 450),
        (14, 35),
    ),
    MaterialGroup(
        "STEEL",
        ("Stainless sheet", "Shaft bar", "Pipe"),
        ("1.4301", "1.4404", "1.4571", "C45"),
        ("2mm", "3mm", "40mm", "DN50"),
        "KG",
        (2, 18),
        (10, 25),
    ),
    MaterialGroup(
        "PACKAGING",
        ("Euro pallet", "Shipping carton", "Stretch film"),
        ("standard", "heavy duty", "recycled"),
        ("S", "M", "L", "XL"),
        "PC",
        (0.5, 25),
        (5, 10),
    ),
]

SERVICE_LINES = [
    ("Pump test bench calibration", (180, 900)),
    ("On-site maintenance service (hours)", (75, 140)),
    ("Engineering consulting (hours)", (95, 180)),
    ("Waste disposal service", (120, 650)),
    ("Express freight surcharge", (40, 400)),
]
