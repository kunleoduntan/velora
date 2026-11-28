"""Cancel a posted document: take it out of the books completely, in one transaction.

This is Velora's version of ERPNext's cancel. When a submitted document is cancelled (the framework has already checked the
`cancel` permission and that no other submitted document still depends on it):

1. the posting period must still be open;
2. every Account Ledger Record it produced is deleted, together with its posting batch (nothing is left behind to reverse);
3. the things that hang on it are unlinked or cleaned up by the rule for its type (see CLEANUP below): settled invoices are
   reopened, receipts that settled a cancelled invoice become unapplied, derived schedules / assets / allocations are removed;
4. a Posting Cancellation Log keeps who, when, why and a copy of what was removed, so an auditor can still see it.

The document itself stays, with status Cancelled, so it can be amended (`amended_from`) or duplicated to post a corrected version.
It is registered once, for every document type, through the `*` doc event in hooks.py.
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from velora import db, get_doc, new_doc, throw
from velora.db.tables import get_table
from velora.meta.registry import registry


class Report:
    """What this cancellation removed or unlinked (shown in the log)."""

    def __init__(self):
        self.unlinked: list[str] = []
        self.ledger_rows = 0
        self.stock_rows = 0
        self.total_debit = 0
        self.snapshot: dict = {"account_ledger": [], "stock_ledger": []}
        self.posting_date = None

    def note(self, text: str):
        self.unlinked.append(text)


def _plain(rows):
    return json.loads(json.dumps([dict(r) for r in rows], default=str))


def _batches_of(doctype: str, name: str) -> list[dict]:
    """Every Financial Posting Batch produced by a document (an Accrual's automatic reversal is one of them)."""
    table = get_table("Financial Posting Batch")
    with db.transaction() as conn:
        return [dict(r) for r in conn.execute(select(table).where(table.c.source_doctype == doctype, table.c.source_name == name)).mappings()]


def assert_period_open(posting_date) -> None:
    """Nothing can be cancelled into a closed Financial Year or Period."""
    from velora_erp.finance.engine import _resolve_period
    try:
        _resolve_period(posting_date)
    except Exception as exc:  # re-worded so it reads as a cancel problem, not a posting problem
        raise type(exc)(str(exc).replace("is not open for posting", "is closed, so documents posted in it cannot be cancelled")) from None


def remove_postings(doc, report: Report) -> None:
    """Delete the document's account ledger rows and posting batches."""
    batches = _batches_of(doc.doctype, doc.name)
    if not batches:
        return
    for b in batches:
        assert_period_open(b["posting_date"])
    names = [b["name"] for b in batches]
    ledger = get_table("Account Ledger Record")
    lines = get_table("Financial Posting Line")
    batch_table = get_table("Financial Posting Batch")
    with db.transaction() as conn:
        rows = list(conn.execute(select(ledger).where(ledger.c.posting_batch.in_(names))).mappings())
        # A cancelled batch must not leave a row pointing at it from anywhere else.
        report.snapshot["account_ledger"] = _plain(rows)
        report.ledger_rows += len(rows)
        report.total_debit += sum(float(r["base_debit"] or 0) for r in rows)
        report.posting_date = max((b["posting_date"] for b in batches), default=None)
        conn.execute(delete(ledger).where(ledger.c.posting_batch.in_(names)))
        conn.execute(delete(lines).where(lines.c.parent.in_(names)))
        conn.execute(delete(batch_table).where(batch_table.c.name.in_(names)))
        # Forget the batch on every record that held its name in a Link field (the document itself first of all).
        for dt, f in registry.links_to("Financial Posting Batch"):
            t = get_table(dt.name)
            conn.execute(update(t).where(t.c[f.fieldname].in_(names)).values({f.fieldname: None}))
    report.note(f"{len(rows)} account ledger rows and {len(names)} posting batch(es) removed")


# ---------------------------------------------------------------------------------------------------------------------
# Rules for what hangs on each type of document. Each is `fn(doc, report)`.
# ---------------------------------------------------------------------------------------------------------------------

def _cancel_derived(doctype: str, filters: dict, report: Report, label: str, *, delete_drafts: bool = True):
    """Cancel (or delete if still a draft) records generated from the document; submitted children go first."""
    from velora import get_list
    for r in get_list(doctype, filters=filters, fields=["name", "docstatus"], limit=10000, ignore_permissions=True):
        d = get_doc(doctype, r["name"], ignore_permissions=True)
        if d.docstatus == 1:
            d.flags.ignore_links = True
            d.cancel(ignore_permissions=True, reason=f"{label} cancelled")
            report.note(f"{doctype} {d.name} cancelled")
        elif d.docstatus == 0 and delete_drafts:
            d.delete(ignore_permissions=True)
            report.note(f"{doctype} {r['name']} removed")


def _recognition(doc, report: Report):
    """Prepayment / deferred-income schedules made from this document, and the periods already recognised from them."""
    from velora import get_list
    for s in get_list("Recognition Schedule", filters={"source_doctype": doc.doctype, "source_document": doc.name},
                      fields=["name", "docstatus"], limit=10000, ignore_permissions=True):
        _cancel_derived("Schedule Recognition", {"schedule": s["name"]}, report, "Recognition Schedule")
    _cancel_derived("Recognition Schedule", {"source_doctype": doc.doctype, "source_document": doc.name}, report, doc.doctype)


def _intercompany(doc, report: Report):
    table = get_table("Intercompany Cost Allocation")
    with db.transaction() as conn:
        found = list(conn.execute(select(table.c.name, table.c.status).where(table.c.source_invoice == doc.name)).all())
        for name, status in found:
            if status not in ("Pending Counterparty Posting", "Cancelled"):
                throw(f"Intercompany Cost Allocation {name} has already been taken up by the other entity ({status}). It must be undone there first.")
        if found:
            conn.execute(delete(table).where(table.c.source_invoice == doc.name))
    for name, _ in found:
        report.note(f"Intercompany Cost Allocation {name} removed")


def _fixed_assets_from_invoice(doc, report: Report):
    """Assets created by a Purchase Invoice go with it, unless they have been used (depreciated, transferred, disposed ...)."""
    table = get_table("Fixed Asset")
    history = get_table("Fixed Asset History Log")
    with db.transaction() as conn:
        assets = list(conn.execute(select(table.c.name, table.c.status).where(table.c.source_purchase == doc.name)).all())
        for name, status in assets:
            other = conn.execute(select(history.c.name).where(history.c.asset == name, history.c.event_type != "Acquisition").limit(1)).first()
            if other or status not in ("Active", "Draft"):
                throw(f"Fixed Asset {name} created by this invoice has already been used ({status}). Reverse its later activity before cancelling the invoice.")
        for name, _ in assets:
            conn.execute(delete(history).where(history.c.asset == name))
    for name, _ in assets:
        _remove_asset(name)
        report.note(f"Fixed Asset {name} removed")


def _remove_asset(name: str) -> None:
    """The asset, its components and book balances go. Cancelled documents that still name it simply keep the text."""
    with db.transaction() as conn:
        for child, column in (("Fixed Asset Component", "parent"), ("Fixed Asset Book Balance", "asset")):
            t = get_table(child)
            conn.execute(delete(t).where(t.c[column] == name))
        t = get_table("Fixed Asset")
        conn.execute(delete(t).where(t.c.name == name))


def _unlink_settlement_from_invoice(doc, report: Report):
    """A cancelled invoice leaves the receipts / payments that settled it as unapplied money (ERPNext: unlink_ref_doc_from_payment_entries)."""
    for parent, child in (("Receipt", "Receipt Line"), ("Payment", "Payment Line")):
        ct, pt, led = get_table(child), get_table(parent), get_table("Account Ledger Record")
        with db.transaction() as conn:
            lines = list(conn.execute(select(ct.c.name, ct.c.parent).where(ct.c.invoice_reference == doc.name, ct.c.parenttype == parent)).all())
            if not lines:
                continue
            parents = sorted({p for _, p in lines})
            conn.execute(update(ct).where(ct.c.name.in_([n for n, _ in lines])).values(invoice_reference=None, allocation_amount=0))
            conn.execute(update(led).where(led.c.source_doctype == parent, led.c.source_name.in_(parents),
                                           led.c.source_line_reference == doc.name).values(source_line_reference=None))
            for p in parents:
                still = conn.execute(select(ct.c.name).where(ct.c.parent == p, ct.c.parenttype == parent, ct.c.invoice_reference.isnot(None)).limit(1)).first()
                if not still:
                    conn.execute(update(pt).where(pt.c.name == p).values(allocation_status=None))
        for p in parents:
            report.note(f"{parent} {p} is no longer applied to {doc.name}; its amount is now unapplied")


def _release_invoice_amounts(doc, direction, report: Report):
    """A cancelled receipt / payment gives the amounts it settled back to the invoices."""
    from velora_erp.finance.invoice_settlement import release_allocations
    released = release_allocations(doc, direction)
    for name, amount in sorted(released.items()):
        report.note(f"Invoice {name} reopened by {amount:,.2f}")


def _refresh_sources(doc, report: Report):
    """Whatever this document was raised from (quotation, order, receipt, delivery) shows its Billed / Received % again."""
    if "lines" in {f.fieldname for f in doc.meta.fields} or getattr(doc, "source_document", None):
        from velora_erp.finance.fulfilment import refresh_for
        refresh_for(doc)


def _lease_instalment(doc, report: Report):
    if doc.doctype == "Payment" and getattr(doc, "purpose", None) == "Lease Payment" and getattr(doc, "lease_reference", None):
        from velora_erp.finance.doctype._utils import db_update, db_update_child
        from velora import get_list
        for later in ("Fixed Asset Lease Modification", "Fixed Asset Lease Termination"):
            hit = [r["name"] for r in get_list(later, filters=[["lease", "=", doc.lease_reference], ["docstatus", "=", 1], ["creation", ">", doc.creation]],
                                               fields=["name"], limit=3, ignore_permissions=True)]
            if hit:
                throw(f"Payment {doc.name} cannot be cancelled: the lease was changed after it ({later} {', '.join(hit)}). Cancel that first (or use Cancel All).")
        lease = get_doc("Fixed Asset Lease", doc.lease_reference, ignore_permissions=True)
        schedule = next((p for p in (lease.payments or []) if str(p.due_date) == str(doc.lease_due_date)), None)
        if schedule:
            db_update_child("Fixed Asset Lease Payment", schedule.name, payment_status="Scheduled", payment_reference=None)
            db_update(lease, lease_liability_balance=schedule.opening_liability)
            report.note(f"Lease instalment due {doc.lease_due_date} on {lease.name} is scheduled again")


def _assets_created_by(doc, report: Report):
    """Assets made by a Fixed Asset Purchase or a Lease go with it, unless they have been used since."""
    table = get_table("Fixed Asset")
    history = get_table("Fixed Asset History Log")
    with db.transaction() as conn:
        assets = list(conn.execute(select(table.c.name, table.c.status).where(table.c.source_purchase == doc.name)).all())
        for name, status in assets:
            other = conn.execute(select(history.c.source_doctype, history.c.source_name).where(
                history.c.asset == name, history.c.source_name != doc.name).limit(1)).first()
            if other or status not in ("Active", "Draft", "Leased"):
                throw(f"Fixed Asset {name} created by {doc.doctype} {doc.name} has been used since "
                      f"({other[0] + ' ' + other[1] if other else status}). Cancel that first (or use Cancel All).")
        for name, _ in assets:
            conn.execute(delete(history).where(history.c.asset == name))
    for name, _ in assets:
        _remove_asset(name)
        report.note(f"Fixed Asset {name} removed")


def _asset_purchase(doc, report):
    _assets_created_by(doc, report)
    if getattr(doc, "request_reference", None) and db.exists("Fixed Asset Request", doc.request_reference):
        from velora_erp.finance.doctype._utils import db_update
        db_update(get_doc("Fixed Asset Request", doc.request_reference, ignore_permissions=True), status="Approved", converted_purchase=None)
        report.note(f"Fixed Asset Request {doc.request_reference} is open again")


def _restore(doc, report):
    from velora_erp.finance import restore_points
    restore_points.restore(doc, report)


def _payroll_run(doc, report):
    """The run's slips are cancelled with it (nothing may have been paid on them); the loans, advances, inputs and credit reviews go back."""
    slips = get_table("Salary Slip")
    with db.transaction() as conn:
        rows = conn.execute(select(slips.c.name, slips.c.paid_amount).where(slips.c.payroll_run == doc.name, slips.c.docstatus == 1)).all()
    for name, paid in rows:
        if paid and float(paid) != 0:
            throw(f"Salary Slip {name} has been paid. Cancel the Payroll Payment first (or use Cancel All).")
    for name, _ in rows:
        slip = get_doc("Salary Slip", name, ignore_permissions=True)
        slip.flags.cancelled_with_run = True
        slip.flags.ignore_links = True
        slip.cancel(ignore_permissions=True, reason=f"Payroll Run {doc.name} cancelled")
        report.note(f"Salary Slip {name} cancelled")
    _restore(doc, report)


def _sales_invoice(doc, report):
    _unlink_settlement_from_invoice(doc, report)
    _recognition(doc, report)


def _purchase_invoice(doc, report):
    _unlink_settlement_from_invoice(doc, report)
    _recognition(doc, report)
    _intercompany(doc, report)
    _fixed_assets_from_invoice(doc, report)


def _receipt(doc, report):
    _release_invoice_amounts(doc, "Receipt", report)
    _recognition(doc, report)


def _payment(doc, report):
    _release_invoice_amounts(doc, "Payment", report)
    _recognition(doc, report)
    _lease_instalment(doc, report)


def _accrual(doc, report):
    from velora_erp.finance.doctype._utils import db_update
    db_update(doc, status="Cancelled", reversal_batch=None)


def _bank_processor(doc, report):
    """A processor made a draft Bank Batch. A draft goes with it; a batch that has been submitted must be cancelled first."""
    name = getattr(doc, "generated_batch", None)
    if not name:
        return
    batch = get_doc("Batch Bank Transaction", name, ignore_permissions=True) if db.exists("Batch Bank Transaction", name) else None
    if batch is None:
        return
    if batch.docstatus == 1:
        throw(f"Bank Batch {name} made from this processor is submitted. Cancel it first (or use Cancel All).")
    if batch.docstatus == 0:
        batch.delete(ignore_permissions=True)
        report.note(f"Draft Bank Batch {name} removed")


CLEANUP = {
    "Bank Transaction Processor": [_bank_processor],
    "Sales Invoice": [_sales_invoice],
    "Purchase Invoice": [_purchase_invoice],
    "Receipt": [_receipt],
    "Payment": [_payment],
    "Accrual": [_accrual],
    "Fixed Asset Purchase": [_asset_purchase],
    "Fixed Asset Lease": [_assets_created_by],
}
CLEANUP["Payroll Run"] = [_payroll_run]


def _tax_journal(doc, report):
    from velora_erp.tax.wht import release_settlements
    release_settlements(doc, report)


CLEANUP["Tax Journal"] = [_tax_journal]


def _fx_revaluation(doc, report):
    from velora_erp.finance.doctype.foreign_currency_revaluation.foreign_currency_revaluation import on_cancelled
    on_cancelled(doc, report)


CLEANUP["Foreign Currency Revaluation"] = [_fx_revaluation]


def _ecl(doc, report):
    from velora_erp.finance.doctype.expected_credit_loss_assessment.expected_credit_loss_assessment import on_cancelled
    on_cancelled(doc, report)


def _provision(doc, report):
    from velora_erp.finance.doctype.provision_entry.provision_entry import on_cancelled
    on_cancelled(doc, report)


CLEANUP["Expected Credit Loss Assessment"] = [_ecl]
CLEANUP["Provision Entry"] = [_provision]


def _treasury(module, doctype):
    def rule(doc, report):
        import importlib
        importlib.import_module(f"velora_erp.treasury.doctype.{module}.{module}").on_cancelled(doc, report)
    CLEANUP[doctype] = [rule]


for _module, _doctype in (("financing_drawdown", "Financing Drawdown"), ("financing_repayment", "Financing Repayment"), ("interest_accrual", "Interest Accrual"), ("facility_amendment", "Facility Amendment")):
    _treasury(_module, _doctype)
for _name in ("Year End Close", "Financial Period Close", "Deferred Tax Posting Inbox"):
    CLEANUP[_name] = [_restore]
for _name in ("Employee Loan Repayment", "Employee Advance Settlement", "Payroll Payment"):
    CLEANUP[_name] = [_restore]
for _name in ("Fixed Asset Depreciation Run", "Fixed Asset Revaluation", "Fixed Asset Impairment", "Fixed Asset Disposal", "Fixed Asset Transfer",
              "Fixed Asset Component Adjustment", "Fixed Asset CGU Impairment", "Fixed Asset CGU Impairment Reversal",
              "Fixed Asset Lease Modification", "Fixed Asset Lease Termination"):
    CLEANUP[_name] = [_restore]


def _after_stock(doc, report):
    """Stock ledger rows are removed by finance.inventory.cancel (registered below when present)."""
    try:
        mod = importlib.import_module("velora_erp.finance.inventory.cancel")
    except ModuleNotFoundError as exc:
        if exc.name != "velora_erp.finance.inventory.cancel":
            raise
        return
    mod.remove_stock(doc, report)


def write_log(doc, report: Report, reason: str):
    from velora.permissions import get_session
    log = new_doc("Posting Cancellation Log", source_doctype=doc.doctype, source_name=doc.name,
                  posting_date=report.posting_date, cancelled_by=get_session().user,
                  cancelled_on=datetime.now(timezone.utc).replace(tzinfo=None), reason=reason,
                  ledger_rows_removed=report.ledger_rows, stock_rows_removed=report.stock_rows,
                  total_debit=report.total_debit, unlinked=report.unlinked, snapshot=report.snapshot)
    log.flags.trusted_source = True
    log.insert(ignore_permissions=True)
    return log


def _mark_cancelled(doc) -> None:
    """A document whose status list has "Cancelled" shows it, so no list or report mistakes it for a live one."""
    meta = registry.get(doc.doctype)
    for name in ("status", "budget_status", "publication_status"):
        field = meta.get_field(name)
        if field is not None and "Cancelled" in (field.choices or []) and getattr(doc, name, None) != "Cancelled":
            from velora_erp.finance.doctype._utils import db_update
            db_update(doc, **{name: "Cancelled"})


def on_any_cancel(doc, method=None):
    """The one `on_cancel` for every document type (hooks.py: doc_events["*"])."""
    if doc.doctype in ("Financial Posting Batch", "Posting Cancellation Log"):
        return
    _mark_cancelled(doc)
    report = Report()
    reason = getattr(doc.flags, "cancellation_reason", None) or "No reason supplied"
    remove_postings(doc, report)
    _after_stock(doc, report)
    for rule in CLEANUP.get(doc.doctype, []):
        rule(doc, report)
    _refresh_sources(doc, report)
    if report.ledger_rows or report.stock_rows or report.unlinked:
        write_log(doc, report, reason)
