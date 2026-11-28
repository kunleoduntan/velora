"""Sales and Purchase Invoices, and the settlement of invoices by Receipts and Payments.

An invoice posts when it is submitted (sales: Dr Receivable / Cr Income + Output VAT; purchase: Dr Expense + Input VAT / Cr Payable) and carries an
OUTSTANDING amount. Receipts and Payments reduce it - the amount is changed only here, under a row lock, so two payments racing for the same
invoice can never settle more than is owed. A submitted invoice cannot be edited; one that has been (part-)settled cannot be cancelled until its
receipts/payments are cancelled first.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select, update

from velora import Document, db, get_doc, get_list, throw
from velora.db.tables import get_table

from . import common as c, ledger

ZERO = Decimal("0")
SIDES = {
    "sales": dict(master="Customer", party_field="customer", party_type="Customer", control="receivable", account_roots=("Income",), tax_type="VAT Output", line_word="income"),
    "purchase": dict(master="Supplier", party_field="supplier", party_type="Supplier", control="payable", account_roots=("Expense", "Asset"), tax_type="VAT Input", line_word="expense / asset"),
}


def status_for(outstanding: Decimal, grand_total: Decimal) -> str:
    return "Paid" if outstanding <= 0 else "Partly Paid" if outstanding < grand_total else "Unpaid"


def settle(doctype: str, name: str, amount: Decimal) -> Decimal:
    """Reduce an invoice's outstanding by `amount` under a row lock. Returns the new outstanding."""
    t = get_table(doctype)
    with db.transaction() as conn:
        row = conn.execute(select(t.c.docstatus, t.c.grand_total, t.c.outstanding).where(t.c.name == name).with_for_update()).mappings().first()
        if row is None or row["docstatus"] != 1:
            throw(f"{doctype} {name} is not a submitted invoice")
        out, grand = c.D(row["outstanding"]), c.D(row["grand_total"])
        new = out - amount
        if new < 0:
            throw(f"{doctype} {name} has only {out:,.2f} outstanding, so {amount:,.2f} cannot be settled against it")
        conn.execute(update(t).where(t.c.name == name).values(outstanding=new, status=status_for(new, grand)))
    return new


def unsettle(doctype: str, name: str, amount: Decimal) -> Decimal:
    t = get_table(doctype)
    with db.transaction() as conn:
        row = conn.execute(select(t.c.docstatus, t.c.grand_total, t.c.outstanding).where(t.c.name == name).with_for_update()).mappings().first()
        if row is None or row["docstatus"] != 1:
            throw(f"{doctype} {name} is not a submitted invoice")
        out, grand = c.D(row["outstanding"]), c.D(row["grand_total"])
        new = out + amount
        if new > grand:
            throw(f"{doctype} {name}: restoring {amount:,.2f} would exceed its total {grand:,.2f}; the settlement records are inconsistent")
        conn.execute(update(t).where(t.c.name == name).values(outstanding=new, status=status_for(new, grand)))
    return new


def invoice_facts(doctype: str, name: str) -> dict | None:
    t = get_table(doctype)
    with db.transaction() as conn:
        r = conn.execute(select(t).where(t.c.name == name)).mappings().first()
    return dict(r) if r else None


class InvoiceDocument(Document):
    SIDE = "sales"

    @property
    def _s(self) -> dict:
        return SIDES[self.SIDE]

    def _party(self):
        return self.get(self._s["party_field"])

    def validate(self):
        s = self._s
        master = get_doc(s["master"], self._party(), ignore_permissions=True)
        if master.status == "Blocked":
            throw(f"{s['master']} {self._party()} is blocked: no new invoices can be raised")
        rows = list(self.items or [])
        if not rows:
            throw("Add at least one item")
        infos = c.accounts_info([r.account for r in rows if r.account] + ([c.get_default("sales_income", required=False)] if self.SIDE == "sales" else []))
        tax_codes = {r.tax_code for r in rows if r.tax_code}
        taxes = {t["name"]: t for t in get_list("Tax Code", filters=[["name", "in", sorted(tax_codes)]], fields=["name", "tax_type", "rate", "account"], limit=500, ignore_permissions=True)} if tax_codes else {}
        net = tax = ZERO
        for n, r in enumerate(rows, 1):
            qty, rate = c.D(r.quantity), c.D(r.rate)
            if qty <= 0:
                throw(f"Row {n}: quantity must be greater than zero")
            if rate <= 0:
                throw(f"Row {n}: rate must be greater than zero")
            r.amount = c.round_money(qty * rate)
            if r.amount <= 0:
                throw(f"Row {n}: the amount rounds to nothing")
            if not r.account and self.SIDE == "sales":
                r.account = c.get_default("sales_income")
                infos.update(c.accounts_info([r.account]))
            if not r.account:
                throw(f"Row {n}: choose the {s['line_word']} account")
            acc = c.check_postable(infos.get(r.account) or c.accounts_info([r.account]).get(r.account), r.account, f"Row {n}")
            if acc["root_type"] not in s["account_roots"] or acc.get("account_type") in ("Receivable", "Payable", "Cash", "Bank", "Tax"):
                throw(f"Row {n}: {r.account} is not a valid {s['line_word']} account for an invoice")
            r.tax_amount = ZERO
            if r.tax_code:
                tc = taxes.get(r.tax_code)
                if tc is None:
                    throw(f"Row {n}: tax code {r.tax_code!r} does not exist")
                if tc["tax_type"] != s["tax_type"]:
                    throw(f"Row {n}: {r.tax_code} is a {tc['tax_type']} code; this invoice needs {s['tax_type']}")
                r.tax_amount = c.round_money(r.amount * c.D(tc["rate"]) / 100)
            net += r.amount
            tax += r.tax_amount
        self.net_total, self.tax_total, self.grand_total = net, tax, net + tax
        if not self.posting_date:
            throw("Enter the invoice date")
        pd = c.to_date(self.posting_date, "Invoice date")
        if not self.due_date:
            self.due_date = pd + timedelta(days=int(master.credit_days or 0))
        elif c.to_date(self.due_date, "Due date") < pd:
            throw("The due date cannot be before the invoice date")
        if self.docstatus == 0:
            self.outstanding, self.status = self.grand_total, "Unpaid"
        if self.SIDE == "purchase":
            self._check_supplier_invoice_no()

    def _check_supplier_invoice_no(self):
        no = (self.supplier_invoice_no or "").strip()
        self.supplier_invoice_no = no or None
        if no:
            flt = [["supplier", "=", self.supplier], ["supplier_invoice_no", "=", no], ["docstatus", "<", 2]]
            if self.name:
                flt.append(["name", "!=", self.name])
            hit = get_list("Purchase Invoice", filters=flt, fields=["name"], limit=1, ignore_permissions=True)
            if hit:
                throw(f"Supplier invoice {no} from {self.supplier} is already recorded as {hit[0]['name']}")

    def _legs(self) -> list[ledger.Leg]:
        s = self._s
        by_account: dict[str, Decimal] = {}
        for r in self.items:
            by_account[r.account] = by_account.get(r.account, ZERO) + r.amount
        tax_by_account: dict[str, Decimal] = {}
        if self.tax_total:
            codes = {t["name"]: t["account"] for t in get_list("Tax Code", fields=["name", "account"], limit=500, ignore_permissions=True)}
            for r in self.items:
                if r.tax_amount:
                    a = codes[r.tax_code]
                    tax_by_account[a] = tax_by_account.get(a, ZERO) + r.tax_amount
        ref = f"{self.doctype} {self.name}"
        legs = []
        sale = self.SIDE == "sales"
        for a, amt in by_account.items():
            legs.append(ledger.Leg(a, credit=amt, remarks=ref) if sale else ledger.Leg(a, debit=amt, remarks=ref))
        for a, amt in tax_by_account.items():
            legs.append(ledger.Leg(a, credit=amt, remarks=ref) if sale else ledger.Leg(a, debit=amt, remarks=ref))
        control = ledger.Leg(c.get_default(s["control"]), party_type=s["party_type"], party=self._party(), remarks=ref)
        if sale:
            control.debit = self.grand_total
        else:
            control.credit = self.grand_total
        legs.append(control)
        return legs

    def before_submit(self):
        self.outstanding, self.status = self.grand_total, "Unpaid"

    def on_submit(self):
        ledger.post(self.doctype, self.name, self.posting_date, self._legs(), self.remarks or "")

    def before_cancel(self):
        current = invoice_facts(self.doctype, self.name)
        if c.D(current["outstanding"]) != c.D(current["grand_total"]):
            throw(f"{self.doctype} {self.name} has been (part-)settled: cancel the receipts/payments that settled it first")
        self.status, self.outstanding = "Cancelled", ZERO

    def on_cancel(self):
        ledger.reverse(self.doctype, self.name, self.remarks or "")
