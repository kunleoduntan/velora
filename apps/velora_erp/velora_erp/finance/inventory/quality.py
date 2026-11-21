"""Quality inspection: readings checked against limits, and the rule that goods needing inspection are not received or delivered without it."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from velora import db, get_doc, new_doc, throw
from velora.db.tables import get_table
from velora.permissions import get_session

ZERO = Decimal("0")


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def prepare(doc) -> None:
    """Work out each reading's outcome, the overall result and the accepted and rejected quantities."""
    if not doc.readings and doc.template:
        template = get_doc("Quality Inspection Template", doc.template)
        for p in template.parameters or []:
            doc.append("readings", {"parameter": p.parameter, "kind": p.kind, "min_value": p.min_value, "max_value": p.max_value, "unit": p.unit})
        doc._link_children()
    failed = False
    for index, row in enumerate(doc.readings or [], 1):
        if row.kind == "Pass/Fail":
            row.outcome = "Pass" if int(row.passed or 0) else "Fail"
        elif row.reading in (None, ""):
            row.outcome = None
        else:
            value = float(row.reading)
            low = None if row.min_value in (None, "") else float(row.min_value)
            high = None if row.max_value in (None, "") else float(row.max_value)
            if low is not None and high is not None and low > high:
                throw(f"Reading {index} ({row.parameter}): the minimum is above the maximum.")
            row.outcome = "Pass" if (low is None or value >= low) and (high is None or value <= high) else "Fail"
        failed = failed or row.outcome == "Fail"
    if failed:
        doc.result = "Rejected"                                     # a failed reading cannot be accepted
    qty = _d(doc.inspected_quantity)
    if qty <= 0:
        throw("Quantity Covered must be greater than zero.")
    doc.accepted_quantity = qty if doc.result == "Accepted" else ZERO
    doc.rejected_quantity = qty - _d(doc.accepted_quantity)
    doc.inspector = get_session().user


def check_reference(doc) -> None:
    ref = get_doc(doc.reference_doctype, doc.reference_name)
    lines = [l for l in (ref.lines or []) if l.item_code == doc.item_code and (not doc.batch or getattr(l, "batch", None) in (None, "", doc.batch))]
    if not lines:
        throw(f"{doc.item_code} is not on {doc.reference_doctype} {doc.reference_name}.")
    if int(ref.docstatus or 0) == 2:
        throw(f"{doc.reference_doctype} {doc.reference_name} is cancelled.")
    if _d(doc.inspected_quantity) > sum((_d(l.quantity) for l in lines), ZERO):
        throw(f"{doc.inspected_quantity} is more than the {sum((_d(l.quantity) for l in lines), ZERO)} of {doc.item_code} on {doc.reference_doctype} {doc.reference_name}.")


def require_complete(doc) -> None:
    for row in doc.readings or []:
        if row.kind != "Pass/Fail" and row.reading in (None, ""):
            throw(f"Enter the reading for {row.parameter} before submitting the inspection.")


def accepted_quantity(doctype: str, name: str, item_code: str, batch: str | None = None) -> tuple[Decimal, Decimal]:
    """(accepted, rejected) quantity of an item across the submitted inspections of a document."""
    t = get_table("Quality Inspection")
    cond = [t.c.docstatus == 1, t.c.reference_doctype == doctype, t.c.reference_name == name, t.c.item_code == item_code]
    if batch:
        cond.append(t.c.batch == batch)
    with db.transaction() as c:
        a, r = c.execute(select(func.coalesce(func.sum(t.c.accepted_quantity), 0), func.coalesce(func.sum(t.c.rejected_quantity), 0)).where(*cond)).one()
    return _d(a), _d(r)


def _flagged(line_item: str, flag: str) -> bool:
    return bool(get_doc("Inventory Item", line_item).get(flag)) if line_item else False


def require_inspections(doc, flag: str) -> None:
    """Stop a Purchase Receipt or Delivery Note when an item that must be inspected has no accepted inspection covering its quantity."""
    needed: dict[tuple, Decimal] = {}
    for line in doc.lines or []:
        if _flagged(getattr(line, "item_code", None), flag):
            key = (line.item_code, getattr(line, "batch", None) or None)
            needed[key] = needed.get(key, ZERO) + _d(line.quantity)
    for (item, batch), qty in needed.items():
        accepted, rejected = accepted_quantity(doc.doctype, doc.name, item, batch)
        if accepted >= qty:
            continue
        if rejected > 0 and accepted == 0:
            throw(f"{item} failed quality inspection ({rejected} rejected) on this {doc.doctype}. Remove it, or return it to the supplier, instead of receiving it.")
        throw(f"{item} must be quality-inspected before this {doc.doctype} is submitted: {accepted} of {qty} accepted so far. "
              f"Use Inspect Goods on this document, accept the inspection and submit it.")


def create_inspections(doc, flag: str, inspection_type: str):
    """Draft inspections for the lines that need one and are not yet fully inspected. Returns the first (they are all created)."""
    made = []
    wanted: dict[tuple, Decimal] = {}
    for line in doc.lines or []:
        if _flagged(getattr(line, "item_code", None), flag):
            key = (line.item_code, getattr(line, "batch", None) or None)
            wanted[key] = wanted.get(key, ZERO) + _d(line.quantity)
    for (item, batch), qty in wanted.items():
        accepted, rejected = accepted_quantity(doc.doctype, doc.name, item, batch)
        t = get_table("Quality Inspection")
        with db.transaction() as c:
            drafts = c.execute(select(func.coalesce(func.sum(t.c.inspected_quantity), 0)).where(
                t.c.docstatus == 0, t.c.reference_doctype == doc.doctype, t.c.reference_name == doc.name, t.c.item_code == item)).scalar()
        left = qty - accepted - _d(drafts)
        if left <= 0:
            continue
        template = get_doc("Inventory Item", item).quality_inspection_template
        made.append(new_doc("Quality Inspection", inspection_type=inspection_type, reference_doctype=doc.doctype, reference_name=doc.name,
                            inspection_date=date.today(), item_code=item, batch=batch, template=template, inspected_quantity=float(left)).insert())
    if not made:
        throw("Nothing needs inspecting here: no item on this document requires it, or every quantity is already inspected.")
    return made[0]
