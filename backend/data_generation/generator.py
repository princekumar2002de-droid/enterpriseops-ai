"""Builds a clean procure-to-pay history, then injects labeled exceptions.

Pipeline (all driven by one seeded RNG -> fully reproducible):
  1. reference data, users, materials, suppliers (+ personas), bank accounts, contracts
  2. purchase orders (incl. a few "repeat orders" = legitimate same-amount look-alikes)
  3. shipments -> goods receipts -> one invoice per shipment (everything matches)
  4. scenarios.apply_all(): inject exceptions and hard negatives, write labels
  5. payments (clean invoices paid on time; exceptions paid late or still open)
  6. inventory snapshot, then IDs are assigned in chronological order
"""

import hashlib
import json
import random
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from faker import Faker

from data_generation import GENERATOR_VERSION, reference
from data_generation.model import Dataset, Label, Profile, Row, dec, money, price
from data_generation.reference import Persona


class Generator:
    def __init__(self, seed: int, profile: Profile) -> None:
        self.seed = seed
        self.profile = profile
        self.rng = random.Random(seed)
        self.fake_de = Faker("de_DE")
        self.fake_de.seed_instance(seed)
        self.fake_us = Faker("en_US")
        self.fake_us.seed_instance(seed + 1)

        self.users: list[Row] = []
        self.materials: list[Row] = []
        self.materials_by_group: dict[str, list[Row]] = defaultdict(list)
        self.suppliers: list[Row] = []
        self.bank_accounts: list[Row] = []
        self.contracts: list[Row] = []
        self.contract_items: list[Row] = []
        self.contract_lookup: dict[tuple[str, str, str], Row] = {}
        self.pos: list[Row] = []
        self.mat_docs: list[Row] = []
        self.invoices: list[Row] = []
        self.payments: list[Row] = []
        self.inventory: list[Row] = []
        self.labels: list[Label] = []

    # ------------------------------------------------------------------ helpers

    def days(self, lo: int, hi: int) -> timedelta:
        return timedelta(days=self.rng.randint(lo, hi))

    def uniform_dec(self, lo: float, hi: float, places: str = "0.01") -> Decimal:
        return dec(self.rng.uniform(lo, hi), places)

    def pick(self, candidates: list[Row], k: int, weight: Any = None) -> list[Row]:
        """Weighted sample without replacement (Efraimidis-Spirakis), deterministic."""
        keyed = []
        for c in candidates:
            w = float(weight(c)) if weight else 1.0
            keyed.append((self.rng.random() ** (1.0 / w), c))
        keyed.sort(key=lambda t: t[0], reverse=True)
        return [c for _, c in keyed[:k]]

    def quota(self, rate: float) -> int:
        return max(self.profile.min_per_scenario, round(rate * self.base_invoice_count))

    def label(
        self,
        invoice: Row,
        item_no: int | None,
        code: str,
        *,
        hard_negative: bool = False,
        **details: Any,
    ) -> None:
        self.labels.append(Label(invoice, item_no, code, hard_negative, details))

    def recompute(self, inv: Row) -> None:
        _, rate = reference.TAX[inv["company_code"]]
        for line in inv["_lines"]:
            line["net_amount"] = money(line["quantity"] * line["unit_price"])
        inv["net_amount"] = sum((li["net_amount"] for li in inv["_lines"]), Decimal("0.00"))
        inv["tax_amount"] = money(inv["net_amount"] * rate)
        inv["gross_amount"] = inv["net_amount"] + inv["tax_amount"]

    def persona(self, supplier_id: str) -> Persona:
        return self.supplier_by_id[supplier_id]["_persona"]  # type: ignore[no-any-return]

    def next_reference(self, supplier: Row, on: date) -> str:
        supplier["_ref_seq"] += 1
        seq = supplier["_ref_seq"]
        style = supplier["_ref_style"]
        if style == 0:
            return f"RE-{on:%y}{seq:05d}"
        if style == 1:
            return f"INV-{on:%Y}-{seq:04d}"
        if style == 2:
            return f"{700000 + seq}"
        return f"{on:%Y}/{seq:05d}"

    # ---------------------------------------------------------------- pipeline

    def run(self) -> Dataset:
        from data_generation import scenarios  # local import: scenarios use Generator

        self._users()
        self._materials()
        self._suppliers()
        self._contracts()
        self._purchase_orders()
        self._shipments_and_invoices()
        self.base_invoice_count = len(self.invoices)
        scenarios.apply_all(self)
        self._payments()
        self._inventory()
        return self._finalize()

    def _users(self) -> None:
        n = 0
        for role_code, count in reference.USERS:
            for _ in range(count):
                n += 1
                first, last = self.fake_de.first_name(), self.fake_de.last_name()
                local = _ascii(f"{first}.{last}").lower().replace(" ", "")
                self.users.append(
                    {
                        "user_id": f"U{n:03d}",
                        "display_name": f"{first} {last}",
                        "email": f"{local}.{n}@{reference.EMAIL_DOMAIN}",
                        "role_code": role_code,
                        "is_active": True,
                    }
                )
        buyers = [u["user_id"] for u in self.users if u["role_code"] == "BUYER"]
        self.buyers = {"DE01": buyers[:-1], "US01": buyers[-1:]}

    def _materials(self) -> None:
        groups = reference.MATERIAL_GROUPS
        capacity = sum(len(g.nouns) * len(g.variants) * len(g.sizes) for g in groups)
        if self.profile.n_materials > 0.8 * capacity:
            msg = f"{self.profile.n_materials} materials requested, catalog allows ~{capacity}"
            raise ValueError(msg)
        # All combinations per group, shuffled; then take groups round-robin.
        pools = []
        for g in groups:
            combos = [(g, f"{n} {v} {z}") for n in g.nouns for v in g.variants for z in g.sizes]
            self.rng.shuffle(combos)
            pools.append(combos)
        i = 0
        while len(self.materials) < self.profile.n_materials:
            pool = pools[i % len(pools)]
            i += 1
            if not pool:
                continue
            g, desc = pool.pop()
            lo, hi = g.price_range
            raw = self.rng.uniform(lo, hi)
            std = dec(raw, "0.0001" if raw < 1 else "0.01")
            row = {
                "material_id": f"M{100001 + len(self.materials)}",
                "description": desc,
                "material_group": g.code,
                "base_uom": g.uom,
                "standard_price": std,
                "_lead": g.lead_days,
            }
            self.materials.append(row)
            self.materials_by_group[g.code].append(row)

    def _suppliers(self) -> None:
        n = self.profile.n_suppliers
        personas = [Persona.FRAUD_SIGNAL]
        for persona, share in reference.PERSONA_SHARES:
            personas += [persona] * max(1, round(n * share))
        personas += [Persona.RELIABLE] * (n - len(personas))
        self.rng.shuffle(personas)
        n_us = max(2, round(n * 0.1))
        us_idx = set(
            self.rng.sample([i for i, p in enumerate(personas) if p != Persona.FRAUD_SIGNAL], n_us)
        )
        group_codes = [g.code for g in reference.MATERIAL_GROUPS]
        names: set[str] = set()
        terms_codes = [t["terms_code"] for t in reference.PAYMENT_TERMS]

        for i, persona in enumerate(personas):
            is_us = i in us_idx
            fake = self.fake_us if is_us else self.fake_de
            name = fake.company()
            while name in names:
                name = fake.company()
            names.add(name)
            if is_us:
                country, vat = "US", f"US{self.rng.randint(10**8, 10**9 - 1)}"
            else:
                country = self.rng.choices(["DE", "AT", "CZ", "IT"], [85, 6, 5, 4])[0]
                vat = f"{country if country != 'AT' else 'ATU'}{self.rng.randint(10**7, 10**8 - 1)}"
            # Round-robin first group guarantees every group has suppliers.
            groups = [group_codes[i % len(group_codes)]]
            if self.rng.random() < 0.4:
                extra = self.rng.choice(group_codes)
                if extra not in groups:
                    groups.append(extra)
            supplier = {
                "supplier_id": f"V{10001 + i}",
                "name": name,
                "country": country,
                "city": fake.city(),
                "vat_id": vat,
                "terms_code": self.rng.choices(terms_codes, [35, 25, 25, 15])[0],
                "created_on": self.profile.window_start - self.days(200, 2500),
                "is_blocked": False,
                "_persona": persona,
                "_company": "US01" if is_us else "DE01",
                "_groups": groups,
                "_weight": self.rng.uniform(0.4, 3.0),
                "_ref_style": self.rng.randint(0, 3),
                "_ref_seq": 0,
            }
            self.suppliers.append(supplier)
            self._add_bank_account(supplier, supplier["created_on"], "MIGRATION")

        # Duplicate vendor master: same VAT ID as a sloppy supplier (a classic data issue).
        original = next(s for s in self.suppliers if s["_persona"] == Persona.SLOPPY)
        dup = dict(original)
        dup.update(
            supplier_id=f"V{10001 + len(self.suppliers)}",
            name=f"{original['name']} Niederlassung Sued",
            created_on=self.profile.window_start - self.days(30, 120),
            _persona=Persona.DUPLICATE_MASTER,
            _weight=0.0,
            _ref_seq=0,
            _original=original,
        )
        self.suppliers.append(dup)
        self.bank_accounts.append(
            {
                **self.bank_accounts[self.suppliers.index(original)],
                "supplier_id": dup["supplier_id"],
                "valid_from": dup["created_on"],
            }
        )
        self.supplier_by_id = {s["supplier_id"]: s for s in self.suppliers}

    def _add_bank_account(self, supplier: Row, valid_from: date, changed_by: str) -> Row:
        if supplier["country"] == "US":
            iban = f"US{self.rng.randint(10**8, 10**9 - 1)}{self.rng.randint(10**9, 10**10 - 1)}"
        else:
            iban = self.fake_de.iban()
        row = {
            "supplier_id": supplier["supplier_id"],
            "iban_masked": f"{iban[:4]} **** **** {iban[-4:]}",
            "iban_hash": hashlib.sha256(iban.encode()).hexdigest(),
            "valid_from": valid_from,
            "valid_to": None,
            "changed_by": changed_by,
        }
        for prev in self.bank_accounts:
            if prev["supplier_id"] == supplier["supplier_id"] and prev["valid_to"] is None:
                prev["valid_to"] = valid_from
        self.bank_accounts.append(row)
        return row

    def _contracts(self) -> None:
        n = 0
        for s in self.suppliers:
            if s["_persona"] == Persona.DUPLICATE_MASTER:
                continue
            if self.rng.random() > (0.6 if s["_company"] == "DE01" else 0.4):
                continue
            n += 1
            header = {
                "contract_id": f"C{4000000 + n}",
                "supplier_id": s["supplier_id"],
                "company_code": s["_company"],
                "valid_from": self.profile.window_start - self.days(30, 300),
                "valid_to": self.profile.window_end + self.days(30, 365),
                "currency": "USD" if s["_company"] == "US01" else "EUR",
                "terms_code": s["terms_code"],
                "document_ref": None,
            }
            self.contracts.append(header)
            pool = [m for g in s["_groups"] for m in self.materials_by_group[g]]
            for j, m in enumerate(self.rng.sample(pool, min(len(pool), self.rng.randint(4, 12)))):
                item = {
                    "contract_id": header["contract_id"],
                    "item_no": (j + 1) * 10,
                    "material_id": m["material_id"],
                    "agreed_price": price(
                        m["standard_price"] * self.uniform_dec(0.88, 1.0, "0.001")
                    ),
                }
                self.contract_items.append(item)
                self.contract_lookup[(s["supplier_id"], s["_company"], m["material_id"])] = item

    def _quantity(self, m: Row) -> Decimal:
        if m["base_uom"] == "KG":
            return Decimal(self.rng.randint(100, 3000))
        p = m["standard_price"]
        if p < 2:
            return Decimal(self.rng.randint(20, 500) * 10)
        if p < 100:
            return Decimal(self.rng.randint(10, 400))
        return Decimal(self.rng.randint(1, 40))

    def _purchase_orders(self) -> None:
        active = [s for s in self.suppliers if s["_persona"] != Persona.DUPLICATE_MASTER]
        weights = [s["_weight"] for s in active]
        span = (self.profile.window_end - self.profile.window_start).days
        for k in range(self.profile.n_purchase_orders):
            s = self.rng.choices(active, weights)[0]
            company = s["_company"]
            doc_date = self.profile.window_start + timedelta(days=self.rng.randint(0, span - 15))
            pool = [m for g in s["_groups"] for m in self.materials_by_group[g]]
            n_items = min(len(pool), self.rng.choices([1, 2, 3, 4, 5], [35, 30, 18, 10, 7])[0])
            mats = self.rng.sample(pool, n_items)
            lead = max(self.rng.randint(*m["_lead"]) for m in mats)
            header = {
                "supplier_id": s["supplier_id"],
                "company_code": company,
                "purch_org": reference.PURCH_ORG[company],
                "doc_date": doc_date,
                "created_by": self.rng.choice(self.buyers[company]),
                "currency": "USD" if company == "US01" else "EUR",
                "terms_code": s["terms_code"],
                "_seq": k,
                "_items": [],
                "_shipments": [],
            }
            for j, m in enumerate(mats):
                contract = self.contract_lookup.get((s["supplier_id"], company, m["material_id"]))
                net_price = (
                    contract["agreed_price"]
                    if contract
                    else price(m["standard_price"] * self.uniform_dec(0.97, 1.12, "0.001"))
                )
                header["_items"].append(
                    {
                        "item_no": (j + 1) * 10,
                        "material_id": m["material_id"],
                        "plant_id": self.rng.choice(reference.PLANTS_BY_COMPANY[company]),
                        "quantity": self._quantity(m),
                        "uom": m["base_uom"],
                        "net_price": net_price,
                        "delivery_date": doc_date + timedelta(days=lead),
                        "gr_based_iv": True,
                        "contract_id": contract["contract_id"] if contract else None,
                        "contract_item_no": contract["item_no"] if contract else None,
                        "tax_code": reference.TAX[company][0],
                        "deletion_flag": False,
                        "_po": header,
                        "_material": m,
                    }
                )
            self.pos.append(header)

        # Repeat orders: same supplier, items, quantities and prices ~3-4 weeks later.
        sources = [p for p in self.pos if p["doc_date"] < self.profile.window_end - timedelta(90)]
        n_repeat = max(self.profile.min_per_scenario, round(0.01 * len(self.pos)))
        for src in self.pick(sources, n_repeat):
            shift = self.days(21, 28)
            rep = {key: v for key, v in src.items() if not key.startswith("_")}
            rep.update(
                doc_date=src["doc_date"] + shift,
                _seq=len(self.pos),
                _items=[],
                _shipments=[],
                _repeat_of=src,
            )
            for it in src["_items"]:
                rep["_items"].append(
                    {**it, "delivery_date": it["delivery_date"] + shift, "_po": rep}
                )
            src["_repeat_source"] = True
            self.pos.append(rep)

    def _shipments_and_invoices(self) -> None:
        end = self.profile.window_end
        for po in self.pos:
            persona = self.persona(po["supplier_id"])
            on_time_p, late_range = reference.DELIVERY[persona]
            promised = po["_items"][0]["delivery_date"]
            delay = (
                self.rng.randint(-2, 0)
                if self.rng.random() < on_time_p
                else self.rng.randint(*late_range)
            )
            first = promised + timedelta(days=delay)
            is_repeat = "_repeat_of" in po or po.get("_repeat_source")
            partial = not is_repeat and self.rng.random() < 0.15
            plan: list[tuple[date, list[tuple[Row, Decimal]]]] = []
            if partial:
                part1, part2 = [], []
                for it in po["_items"]:
                    q = it["quantity"]
                    q1 = Decimal(int(q * self.uniform_dec(0.5, 0.8))) if q > 1 else q
                    part1.append((it, q1))
                    if q - q1 > 0:
                        part2.append((it, q - q1))
                plan.append((first, part1))
                if part2:
                    plan.append((first + self.days(7, 20), part2))
            else:
                plan.append((first, [(it, it["quantity"]) for it in po["_items"]]))

            for ship_date, lines in plan:
                if ship_date > end:
                    break
                shipment = {"po": po, "date": ship_date, "partial": len(plan) > 1}
                doc = self._mat_doc(ship_date, [(it, q, "101", None) for it, q in lines])
                shipment["mat_doc"] = doc
                po["_shipments"].append(shipment)
                self._invoice_for_shipment(shipment, doc)

    def _mat_doc(self, on: date, lines: list[tuple[Row, Decimal, str, Row | None]]) -> Row:
        doc: Row = {"date": on, "lines": [], "_seq": len(self.mat_docs)}
        for it, qty, mvt, ref in lines:
            doc["lines"].append(
                {
                    "_po_item": it,
                    "movement_type": mvt,
                    "quantity": qty,
                    "posting_date": on,
                    "plant_id": it["plant_id"],
                    "_ref": ref,
                    "_doc": doc,
                }
            )
        self.mat_docs.append(doc)
        return doc

    def _invoice_for_shipment(self, shipment: Row, doc: Row) -> None:
        po = shipment["po"]
        supplier = self.supplier_by_id[po["supplier_id"]]
        invoice_date = shipment["date"] + self.days(0, 4)
        received = invoice_date + self.days(1, 6)
        if received > self.profile.window_end:
            return
        posting = received + self.days(0, 2)
        inv: Row = {
            "doc_type": "INVOICE",
            "supplier_id": po["supplier_id"],
            "company_code": po["company_code"],
            "supplier_reference": self.next_reference(supplier, invoice_date),
            "invoice_date": invoice_date,
            "received_date": received,
            "posting_date": posting if posting <= self.profile.window_end else None,
            "currency": po["currency"],
            "terms_code": po["terms_code"],
            "status": "RECEIVED",
            "payment_block": None,
            "_po": po,
            "_shipment": shipment,
            "_lines": [],
            "_used": False,
            "_seq": len(self.invoices),
        }
        for n, gr in enumerate(doc["lines"], start=1):
            it = gr["_po_item"]
            inv["_lines"].append(
                {
                    "item_no": n,
                    "_po_item": it,
                    "material_id": it["material_id"],
                    "description": it["_material"]["description"],
                    "quantity": gr["quantity"],
                    "unit_price": it["net_price"],
                    "tax_code": it["tax_code"],
                    "_gr": gr,
                }
            )
        self.recompute(inv)
        shipment["invoice"] = inv
        self.invoices.append(inv)

    def _payments(self) -> None:
        end = self.profile.window_end
        exception_ids = {id(lb.invoice) for lb in self.labels if not lb.hard_negative}
        unpaid_codes = {"DUPLICATE_SUSPECTED", "BANK_DETAILS_CHANGED"}
        never_pay = {id(lb.invoice) for lb in self.labels if lb.code in unpaid_codes}
        credit_by_invoice: dict[int, Decimal] = defaultdict(Decimal)
        for inv in self.invoices:
            if inv["doc_type"] == "CREDIT_MEMO":
                credit_by_invoice[id(inv["_reference"])] += inv["gross_amount"]

        for inv in sorted(self.invoices, key=lambda i: i["_seq"]):
            if inv["doc_type"] != "INVOICE" or id(inv) in never_pay:
                continue
            terms = reference.TERMS_BY_CODE[inv["terms_code"]]
            gross = inv["gross_amount"] - credit_by_invoice[id(inv)]
            discount = Decimal("0.00")
            if id(inv) in exception_ids:
                pay_date = inv["received_date"] + self.days(12, 55)
            elif terms["discount_days"] and self.rng.random() < 0.55:
                pay_date = inv["invoice_date"] + self.days(2, terms["discount_days"])
                discount = money(gross * terms["discount_pct"] / 100)
            else:
                # Payment runs pay on or before the due date; ~8 % are paid late on purpose.
                pay_date = (
                    inv["invoice_date"] + timedelta(days=terms["net_days"]) + self.days(-5, 0)
                )
                if self.rng.random() < 0.08:
                    pay_date += self.days(5, 25)
            pay_date = max(pay_date, inv["received_date"] + timedelta(days=1))
            if pay_date > end or gross - discount <= 0:
                continue
            self.payments.append(
                {
                    "_invoice": inv,
                    "payment_date": pay_date,
                    "amount": gross - discount,
                    "discount_taken": discount,
                    "currency": inv["currency"],
                }
            )
            inv["status"] = "PAID"

    def _inventory(self) -> None:
        for plant in reference.PLANTS:
            for m in self.materials:
                if self.rng.random() < 0.5:
                    continue
                self.inventory.append(
                    {
                        "material_id": m["material_id"],
                        "plant_id": plant["plant_id"],
                        "as_of": self.profile.window_end,
                        "quantity": self._quantity(m),
                    }
                )

    # ---------------------------------------------------------------- finalize

    def _finalize(self) -> Dataset:
        for n, po in enumerate(sorted(self.pos, key=lambda p: (p["doc_date"], p["_seq"]))):
            po["po_number"] = f"{4500000001 + n}"
            for it in po["_items"]:
                it["po_number"] = po["po_number"]

        goods_receipts: list[Row] = []
        for n, doc in enumerate(sorted(self.mat_docs, key=lambda d: (d["date"], d["_seq"]))):
            doc["mat_doc"] = f"{5000000001 + n}"
            for line_no, gr in enumerate(doc["lines"], start=1):
                gr.update(mat_doc=doc["mat_doc"], mat_doc_year=doc["date"].year, line_no=line_no)
        for doc in self.mat_docs:
            for gr in doc["lines"]:
                ref = gr["_ref"]
                gr.update(
                    po_number=gr["_po_item"]["po_number"],
                    po_item_no=gr["_po_item"]["item_no"],
                    ref_mat_doc=ref["mat_doc"] if ref else None,
                    ref_mat_doc_year=ref["mat_doc_year"] if ref else None,
                    ref_line_no=ref["line_no"] if ref else None,
                )
                goods_receipts.append(gr)

        ordered = sorted(
            self.invoices,
            key=lambda i: (i["received_date"], i["invoice_date"], i["supplier_id"], i["_seq"]),
        )
        invoice_items: list[Row] = []
        for n, inv in enumerate(ordered):
            inv["invoice_id"] = f"{5100000001 + n}"
        for inv in ordered:
            ref = inv.get("_reference")
            inv["reference_invoice_id"] = ref["invoice_id"] if ref else None
            for line in inv["_lines"]:
                it = line.get("_po_item")
                line.update(
                    invoice_id=inv["invoice_id"],
                    po_number=it["po_number"] if it else None,
                    po_item_no=it["item_no"] if it else None,
                )
                invoice_items.append(line)

        payments = sorted(
            self.payments, key=lambda p: (p["payment_date"], p["_invoice"]["invoice_id"])
        )
        for n, p in enumerate(payments):
            p.update(payment_id=f"PAY{1000001 + n}", invoice_id=p["_invoice"]["invoice_id"])

        po_items = [it for po in self.pos for it in po["_items"]]
        tables: dict[str, list[Row]] = {
            "erp.company_code": reference.COMPANY_CODES,
            "erp.plant": reference.PLANTS,
            "erp.payment_terms": reference.PAYMENT_TERMS,
            "erp.supplier": self.suppliers,
            "erp.supplier_bank_account": self.bank_accounts,
            "erp.material": self.materials,
            "erp.contract_header": self.contracts,
            "erp.contract_item": self.contract_items,
            "erp.purchase_order_header": self.pos,
            "erp.purchase_order_item": po_items,
            "erp.goods_receipt": goods_receipts,
            "erp.invoice_header": ordered,
            "erp.invoice_item": invoice_items,
            "erp.payment": payments,
            "erp.inventory_level": self.inventory,
            "iam.app_user": self.users,
            "ops.tolerance_rule": [
                {**rule, "company_code": cc["company_code"]}
                for cc in reference.COMPANY_CODES
                for rule in reference.TOLERANCE_RULES
            ],
        }
        clean = {
            name: sorted(
                ({k: v for k, v in row.items() if not k.startswith("_")} for row in rows),
                key=_sort_key(name),
            )
            for name, rows in tables.items()
        }
        for rows in clean.values():  # mat-doc rows carry a helper key "_doc" already removed
            for row in rows:
                row.pop("lines", None)
        labels = [
            {
                "invoice_id": lb.invoice["invoice_id"],
                "item_no": lb.item_no,
                "label_code": lb.code,
                "is_hard_negative": lb.hard_negative,
                "details": _json_safe(lb.details),
            }
            for lb in sorted(
                self.labels, key=lambda lb: (lb.invoice["invoice_id"], lb.item_no or 0, lb.code)
            )
        ]
        personas = [
            {"supplier_id": s["supplier_id"], "persona": str(s["_persona"])} for s in self.suppliers
        ]
        return Dataset(self.seed, self.profile, clean, labels, personas)


PRIMARY_KEYS = {
    "erp.company_code": ("company_code",),
    "erp.plant": ("plant_id",),
    "erp.payment_terms": ("terms_code",),
    "erp.supplier": ("supplier_id",),
    "erp.supplier_bank_account": ("supplier_id", "valid_from"),
    "erp.material": ("material_id",),
    "erp.contract_header": ("contract_id",),
    "erp.contract_item": ("contract_id", "item_no"),
    "erp.purchase_order_header": ("po_number",),
    "erp.purchase_order_item": ("po_number", "item_no"),
    "erp.goods_receipt": ("mat_doc", "line_no"),
    "erp.invoice_header": ("invoice_id",),
    "erp.invoice_item": ("invoice_id", "item_no"),
    "erp.payment": ("payment_id",),
    "erp.inventory_level": ("material_id", "plant_id"),
    "iam.app_user": ("user_id",),
    "ops.tolerance_rule": ("company_code", "tolerance_key"),
}


def _sort_key(table: str) -> Any:
    cols = PRIMARY_KEYS[table]
    return lambda row: tuple(str(row[c]) for c in cols)


def _ascii(text: str) -> str:
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = text.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        if "invoice_id" in value and "_lines" in value:  # a referenced invoice row
            return value["invoice_id"]
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, Decimal | date):
        return str(value)
    return value


def content_hash(dataset: Dataset) -> str:
    payload = {"tables": dataset.tables, "labels": dataset.labels, "personas": dataset.personas}
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def generate(seed: int, profile: Profile) -> Dataset:
    return Generator(seed, profile).run()


__all__ = ["GENERATOR_VERSION", "Generator", "content_hash", "generate"]
