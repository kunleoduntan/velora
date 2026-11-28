"""Buying by quotation: Request for Quotation -> Supplier Quotation -> Purchase Order.

A Material Request for purchase can become a Request for Quotation sent to several suppliers. Each supplier's reply is recorded as a
Supplier Quotation; the Quotation Comparison report ranks them item by item; ordering from one marks it Awarded and the others Lost.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, update

from velora import db, get_doc, get_list, new_doc, throw
from velora.db.tables import get_table

ZERO = Decimal("0")


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def create_rfq_from_request(request_name: str, overrides: dict | None = None):
    overrides = dict(overrides or {})
    req = get_doc("Material Request", request_name, ignore_permissions=True)
    if req.request_type != "Purchase" or req.request_status != "Approved":
        throw("Only an approved purchase Material Request can be sent out for quotation.")
    from velora_erp.finance.inventory.requests import converted_quantities
    done = converted_quantities(request_name)
    items = []
    for ln in req.lines or []:
        left = _d(ln.quantity) - done.get(str(ln.name), ZERO)
        if left > 0:
            items.append({"item_code": ln.item_code, "quantity": float(left), "uom": ln.uom, "required_by": ln.required_by or req.required_by,
                          "warehouse": ln.warehouse or req.target_warehouse, "source_line": str(ln.name)})
    if not items:
        throw("Everything on this Material Request has already been ordered.")
    suppliers = [s for s in ([overrides.get("supplier")] + list(overrides.get("suppliers") or [])) if s]
    if not suppliers:                                              # fall back on the items' preferred suppliers
        for it in items:
            pref = get_doc("Inventory Item", it["item_code"]).preferred_supplier
            if pref and pref not in suppliers:
                suppliers.append(pref)
    if not suppliers:
        throw("Choose at least one supplier to ask (you can add more on the request afterwards).")
    doc = new_doc("Request for Quotation", transaction_date=date.today(), required_by=req.required_by, material_request=req.name,
                  items=items, suppliers=[{"supplier": s} for s in dict.fromkeys(suppliers)], message=f"Please quote for the items below (Material Request {req.name}).")
    return doc.insert()


def create_quotation_from_rfq(rfq_name: str, overrides: dict | None = None):
    overrides = dict(overrides or {})
    rfq = get_doc("Request for Quotation", rfq_name, ignore_permissions=True)
    supplier = overrides.get("supplier")
    if not supplier:
        asked = [s.supplier for s in rfq.suppliers if s.response != "Quoted"] or [s.supplier for s in rfq.suppliers]
        if len(asked) == 1:
            supplier = asked[0]
    if not supplier:
        throw("Choose the supplier whose quotation you are recording.")
    base = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
    doc = new_doc("Supplier Quotation", supplier=supplier, request_for_quotation=rfq.name, quotation_date=date.today(),
                  currency=base[0]["base_currency"] if base else None, exchange_rate=1, status="Draft",
                  lines=[{"item_code": i.item_code, "quantity": i.quantity, "uom": i.uom, "rate": 0, "warehouse": i.warehouse, "rfq_line": str(i.name)} for i in rfq.items])
    return doc.insert()


def after_quotation_saved(sq) -> None:
    """A quotation that is Received counts: the request moves on and the supplier is ticked off. A newer one from the same supplier replaces the older."""
    if sq.status != "Received":
        return
    q, rt, st = get_table("Supplier Quotation"), get_table("Request for Quotation"), get_table("RFQ Supplier")
    with db.transaction() as c:
        c.execute(update(q).where(q.c.request_for_quotation == sq.request_for_quotation, q.c.supplier == sq.supplier, q.c.status == "Received", q.c.name != sq.name)
                  .values(status="Expired"))
        have = c.execute(select(st.c.name).where(st.c.parent == sq.request_for_quotation, st.c.parenttype == "Request for Quotation", st.c.supplier == sq.supplier)).first()
        if have:
            c.execute(update(st).where(st.c.name == have[0]).values(response="Quoted", quotation=sq.name))
        c.execute(update(rt).where(rt.c.name == sq.request_for_quotation, rt.c.status.in_(["Draft", "Sent"])).values(status="Quotations Received"))
    if not have:                                                    # a supplier that was not on the list quoted anyway: add them
        rfq = get_doc("Request for Quotation", sq.request_for_quotation, ignore_permissions=True)
        rfq.append("suppliers", {"supplier": sq.supplier, "response": "Quoted", "quotation": sq.name})
        rfq.save(ignore_permissions=True)


def award(quotation_name: str, overrides: dict | None = None):
    """Order from this quotation. The quotation is Awarded, the others for the same request are Lost, and the request is Awarded."""
    sq = get_doc("Supplier Quotation", quotation_name, ignore_permissions=True)
    if sq.status != "Received":
        throw("Only a quotation that has been received (and not already awarded, lost or expired) can be ordered from.")
    if sq.valid_till and sq.valid_till < date.today():
        throw(f"This quotation was valid until {sq.valid_till}. Ask the supplier to confirm it, or record a new quotation.")
    rfq = get_doc("Request for Quotation", sq.request_for_quotation, ignore_permissions=True)
    if rfq.status in ("Awarded", "Cancelled"):
        throw(f"Request for Quotation {rfq.name} is {rfq.status.lower()}.")
    wanted = {str(i.name): i for i in rfq.items}
    lines = []
    for ln in sq.lines:
        src = wanted.get(str(ln.rfq_line))
        lead = int(ln.lead_time_days or 0)
        name = get_doc("Inventory Item", ln.item_code).item_name
        lines.append({"source_line": src.source_line if src else None, "item_code": ln.item_code, "item_name": name, "description": name or ln.item_code,
                      "quantity": ln.quantity, "uom": ln.uom, "rate": ln.rate, "warehouse": ln.warehouse or (src.warehouse if src else None),
                      "schedule_date": (src.required_by if src and src.required_by else date.today() + timedelta(days=lead))})
    po = new_doc("Purchase Order", document_date=date.today(), party=sq.supplier, currency=sq.currency, exchange_rate=sq.exchange_rate or 1,
                 material_request=rfq.material_request, source_doctype="Supplier Quotation", source_document=sq.name,
                 narration=f"From Supplier Quotation {sq.name} (Request for Quotation {rfq.name})", lines=lines).insert()
    q, rt = get_table("Supplier Quotation"), get_table("Request for Quotation")
    with db.transaction() as c:
        c.execute(update(q).where(q.c.name == sq.name).values(status="Awarded", purchase_order=po.name))
        c.execute(update(q).where(q.c.request_for_quotation == rfq.name, q.c.status == "Received", q.c.name != sq.name).values(status="Lost"))
        c.execute(update(rt).where(rt.c.name == rfq.name).values(status="Awarded", awarded_quotation=sq.name))
    if rfq.material_request:
        try:
            from velora_erp.finance.inventory.requests import refresh_fulfilment
            refresh_fulfilment(rfq.material_request)
        except Exception:  # noqa: BLE001 - fulfilment is recalculated when the order is next touched
            pass
    return po


def expire_quotations() -> int:
    """Daily task: a received quotation past its valid-until date can no longer be ordered from."""
    q = get_table("Supplier Quotation")
    with db.transaction() as c:
        return c.execute(update(q).where(q.c.status == "Received", q.c.valid_till.isnot(None), q.c.valid_till < date.today()).values(status="Expired")).rowcount


def comparison_rows(rfq_name: str) -> list[dict]:
    """One row per item and quoting supplier, ranked by price in the base currency (1 = cheapest)."""
    rfq = get_doc("Request for Quotation", rfq_name)
    wanted = {str(i.name): i for i in rfq.items}
    rows = []
    for sq in get_list("Supplier Quotation", filters=[["request_for_quotation", "=", rfq_name], ["status", "in", ["Received", "Awarded"]]],
                       fields=["name"], limit=1000, ignore_permissions=True):
        doc = get_doc("Supplier Quotation", sq["name"], ignore_permissions=True)
        for ln in doc.lines or []:
            src = wanted.get(str(ln.rfq_line))
            rows.append({"item_code": ln.item_code, "supplier": doc.supplier, "quotation": doc.name, "status": doc.status, "currency": doc.currency,
                         "quoted_quantity": float(_d(ln.quantity)), "requested_quantity": float(_d(src.quantity)) if src else None,
                         "rate": float(_d(ln.rate)), "rate_base": float(_d(ln.rate) * _d(doc.exchange_rate or 1)), "amount": float(_d(ln.amount)),
                         "lead_time_days": ln.lead_time_days, "valid_till": doc.valid_till})
    by_item: dict[str, list] = {}
    for r in rows:
        by_item.setdefault(r["item_code"], []).append(r)
    for group in by_item.values():
        for rank, r in enumerate(sorted(group, key=lambda x: (x["rate_base"], x["lead_time_days"] or 0)), 1):
            r["rank"] = rank
    return sorted(rows, key=lambda r: (r["item_code"], r["rank"]))
