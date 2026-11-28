"""Material Request fulfilment, conversion and Stock Entry posting.

Approval of a request or entry is decided by the GUI workflow, never here. This module only does the arithmetic:
how much of a request has been converted, and the stock and accounting postings of a submitted Stock Entry.
"""
from __future__ import annotations
from decimal import Decimal
from velora import db, get_doc, get_list, new_doc, throw
from velora.db.tables import get_table
from sqlalchemy import select


def _q(v): return Decimal(str(v if v not in (None, "") else 0))


def converted_quantities(request_name: str) -> dict[str, Decimal]:
    """Quantity already converted from each request line, across purchase orders, stock transfers and stock entries."""
    totals: dict[str, Decimal] = {}
    for doctype in ("Purchase Order", "Stock Transfer", "Stock Entry"):
        for row in get_list(doctype, filters={"material_request": request_name}, fields=["name", "docstatus"], limit=100000, ignore_permissions=True):
            if int(row.get("docstatus") or 0) == 2: continue
            for ln in get_doc(doctype, row["name"], ignore_permissions=True).lines or []:
                key = str(getattr(ln, "source_line", "") or "")
                if key: totals[key] = totals.get(key, Decimal("0")) + _q(getattr(ln, "quantity", 0))
    return totals


def refresh_fulfilment(request_name: str) -> None:
    from velora_erp.finance.doctype._utils import db_update
    doc = get_doc("Material Request", request_name, ignore_permissions=True)
    done = converted_quantities(request_name)
    ordered = Decimal("0"); fulfilled = Decimal("0")
    table = get_table("Material Request Line")
    with db.transaction() as conn:
        for ln in doc.lines or []:
            got = done.get(str(ln.name), Decimal("0"))
            conn.execute(table.update().where(table.c.name == ln.name).values(fulfilled_quantity=float(got)))
            ordered += _q(ln.quantity); fulfilled += min(got, _q(ln.quantity))
    status = "Fulfilled" if ordered and fulfilled >= ordered else "Partially Fulfilled" if fulfilled > 0 else "Not Started"
    if status != doc.fulfilment_status: db_update(doc, fulfilment_status=status)


def create_from_request(request_name: str, target: str, overrides: dict | None = None):
    """Create a draft Purchase Order, Stock Transfer or Stock Entry for what is still outstanding on an approved request."""
    overrides = dict(overrides or {})
    req = get_doc("Material Request", request_name, ignore_permissions=True)
    if req.request_status not in ("Approved",):
        throw("Only an approved Material Request can be converted.")
    expected = {"Purchase": "Purchase Order", "Material Transfer": "Stock Transfer", "Material Issue": "Stock Entry"}[req.request_type]
    if target != expected: throw(f"A {req.request_type} request is converted to a {expected}.")
    done = converted_quantities(request_name)
    lines = []
    for ln in req.lines or []:
        left = _q(ln.quantity) - done.get(str(ln.name), Decimal("0"))
        if left > 0: lines.append((ln, float(left)))
    if not lines: throw("Everything on this Material Request has already been converted.")
    from datetime import date
    today = date.today()
    if target == "Purchase Order":
        supplier = overrides.get("party") or overrides.get("supplier")
        if not supplier: throw("Choose the supplier to order from.")
    return _build(req, target, lines, overrides, today)


def _build(req, target, lines, overrides, today):
    if target == "Purchase Order":
        base = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
        po = new_doc("Purchase Order", document_date=today, party=overrides.get("party") or overrides.get("supplier"),
                     currency=base[0]["base_currency"] if base else None, exchange_rate=1, material_request=req.name,
                     source_doctype="Material Request", source_document=req.name, narration=f"From Material Request {req.name}",
                     lines=[{"source_line": str(ln.name), "item_code": ln.item_code, "item_name": ln.item_name, "description": ln.item_name or ln.item_code,
                             "quantity": qty, "uom": ln.uom, "rate": float(ln.estimated_rate or 0), "warehouse": ln.warehouse or req.target_warehouse,
                             "cost_centre": req.cost_centre, "schedule_date": ln.required_by or req.required_by} for ln, qty in lines])
        return po.insert()
    if target == "Stock Transfer":
        if not (req.source_warehouse and req.target_warehouse): throw("Set the source and target warehouse on the request before converting it.")
        st = new_doc("Stock Transfer", posting_date=today, source_warehouse=req.source_warehouse, target_warehouse=req.target_warehouse,
                     material_request=req.name, approval_status="Pending", remarks=f"From Material Request {req.name}",
                     lines=[{"source_line": str(ln.name), "item_code": ln.item_code, "quantity": qty, "uom": ln.uom} for ln, qty in lines])
        return st.insert()
    se = new_doc("Stock Entry", stock_entry_type="Material Issue", posting_date=today, warehouse=overrides.get("warehouse") or req.source_warehouse,
                 department=req.department, cost_centre=req.cost_centre, material_request=req.name, remarks=f"From Material Request {req.name}",
                 lines=[{"source_line": str(ln.name), "item_code": ln.item_code, "quantity": qty, "uom": ln.uom, "cost_centre": req.cost_centre} for ln, qty in lines])
    return se.insert()


def _ledger_values(voucher: str) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for r in get_list("Stock Ledger Record", filters={"voucher_type": "Stock Entry", "voucher_no": voucher}, fields=["voucher_detail_no", "stock_value_difference"], limit=100000, ignore_permissions=True):
        out[r["voucher_detail_no"]] = out.get(r["voucher_detail_no"], Decimal("0")) + _q(r["stock_value_difference"])
    return out


def post_stock_entry(entry) -> None:
    from velora_erp.finance.inventory.ledger import post_stock_movement, inventory_settings, _post_inventory_accounting, _asset_account, money
    settings = inventory_settings()
    receipt = entry.stock_entry_type == "Material Receipt"
    post_stock_movement(source=entry, posting_date=entry.posting_date, warehouse=entry.warehouse, lines=list(entry.lines or []),
                        direction=1 if receipt else -1, rate_field="basic_rate" if receipt else None, accounting_event=None,
                        remarks=f"{entry.stock_entry_type} {entry.name}")
    values = _ledger_values(entry.name)
    totals: dict[str, list] = {}
    grand = Decimal("0")
    for ln in entry.lines or []:
        amount = abs(values.get(ln.name, Decimal("0")))
        if not amount: continue
        item = get_doc("Inventory Item", ln.item_code, ignore_permissions=True)
        asset = _asset_account(item, settings)
        if receipt:
            other = entry.source_account or settings.get("stock_adjustment_gain_account")
            debit, credit = asset, other
        else:
            if entry.stock_entry_type == "Scrap":
                other = ln.expense_account or settings.get("stock_adjustment_loss_account")
            else:
                other = ln.expense_account or item.expense_account
            if not other: throw(f"Choose the expense account for {ln.item_code} (or set one on the item or in Inventory Settings).")
            debit, credit = other, asset
        if not debit or not credit: throw("Configure the stock adjustment accounts in Inventory Settings before posting this entry.")
        totals.setdefault(debit, [Decimal("0"), Decimal("0")])[0] += amount
        totals.setdefault(credit, [Decimal("0"), Decimal("0")])[1] += amount
        grand += amount
    lines = []
    for account, (dr, cr) in totals.items():
        net = money(dr - cr)
        if net > 0: lines.append({"account": account, "debit": net, "credit": Decimal("0"), "line_description": entry.stock_entry_type, "cost_centre": entry.cost_centre})
        elif net < 0: lines.append({"account": account, "debit": Decimal("0"), "credit": abs(net), "line_description": entry.stock_entry_type, "cost_centre": entry.cost_centre})
    if lines:
        base = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
        if not base: throw("Finance Settings must be configured before inventory posting.")
        _post_inventory_accounting(entry, entry.posting_date, base[0]["base_currency"], 1, lines, "Adjustment", f"{entry.stock_entry_type} {entry.name}")
    from velora_erp.finance.doctype._utils import db_update
    db_update(entry, total_value=float(grand))


# ---- reorder planning and ageing -------------------------------------------------------------------------------

def _on_hand_by_item() -> dict[str, Decimal]:
    from velora_erp.finance.inventory.ledger import get_stock_balances
    out: dict[str, Decimal] = {}
    for r in get_stock_balances():
        out[r["item_code"]] = out.get(r["item_code"], Decimal("0")) + _q(r["qty"])
    return out


def _open_purchase_quantities() -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """(on order, requested) per item: unreceived purchase order lines and approved purchase requests not yet ordered."""
    ordered: dict[str, Decimal] = {}; requested: dict[str, Decimal] = {}
    for po in get_list("Purchase Order", filters=[["docstatus", "!=", 2]], fields=["name", "document_status"], limit=100000, ignore_permissions=True):
        if po.get("document_status") in ("Completed", "Closed"): continue
        for ln in get_doc("Purchase Order", po["name"], ignore_permissions=True).lines or []:
            if ln.item_code: ordered[ln.item_code] = ordered.get(ln.item_code, Decimal("0")) + _q(ln.quantity)
    for mr in get_list("Material Request", filters=[["request_type", "=", "Purchase"], ["request_status", "in", ["Pending Approval", "Approved"]]], fields=["name"], limit=100000, ignore_permissions=True):
        for ln in get_doc("Material Request", mr["name"], ignore_permissions=True).lines or []:
            left = _q(ln.quantity) - _q(ln.fulfilled_quantity)
            if left > 0: requested[ln.item_code] = requested.get(ln.item_code, Decimal("0")) + left
    return ordered, requested


def reorder_rows(item_group=None, show_all=False) -> list[dict]:
    flt = [["disabled", "=", 0], ["is_stock_item", "=", 1], ["reorder_level", ">", 0]]
    if item_group: flt.append(["item_group", "=", item_group])
    items = get_list("Inventory Item", filters=flt, fields=["name", "item_name", "item_group", "reorder_level", "reorder_qty", "maximum_stock_level", "preferred_supplier"], limit=100000, ignore_permissions=True)
    hand = _on_hand_by_item(); ordered, requested = _open_purchase_quantities(); rows = []
    for it in items:
        oh = hand.get(it["name"], Decimal("0")); lvl = _q(it["reorder_level"]); oo = ordered.get(it["name"], Decimal("0")); rq = requested.get(it["name"], Decimal("0"))
        projected = oh + oo + rq
        below = oh <= lvl
        need = Decimal("0")
        if below and projected <= lvl:
            need = _q(it.get("reorder_qty") or 0)
            if need <= 0: need = max(Decimal("0"), (_q(it.get("maximum_stock_level") or 0) or lvl * 2) - projected)
        status = "Order now" if need > 0 else ("Covered by open orders" if below else "OK")
        if show_all or below:
            rows.append({"item_code": it["name"], "item_name": it["item_name"], "item_group": it.get("item_group"), "on_hand": float(oh), "reorder_level": float(lvl),
                         "on_order": float(oo), "requested": float(rq), "to_order": float(need), "preferred_supplier": it.get("preferred_supplier") or "", "status": status})
    return sorted(rows, key=lambda r: (r["status"] != "Order now", r["item_code"]))


def create_reorder_requests(warehouse: str | None = None) -> list[str]:
    """Draft one purchase Material Request from every item that needs ordering. The request then follows the normal approval workflow."""
    from datetime import date
    need = [r for r in reorder_rows() if r["to_order"] > 0]
    if not need: return []
    req = new_doc("Material Request", request_type="Purchase", request_date=date.today(), request_status="Draft", target_warehouse=warehouse,
                  purpose="Raised automatically from items at their reorder level",
                  lines=[{"item_code": r["item_code"], "quantity": r["to_order"], "warehouse": warehouse, "note": f"On hand {r['on_hand']:g}, reorder level {r['reorder_level']:g}"} for r in need])
    req.insert()
    return [req.name]


def ageing_rows(warehouse=None, item_code=None, as_of=None) -> list[dict]:
    from datetime import date, datetime
    from velora_erp.finance.inventory.ledger import get_stock_balances
    day = (as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of)[:10])) if as_of else date.today()
    out = []
    for bal in get_stock_balances(item_code=item_code, warehouse=warehouse):
        qty = _q(bal["qty"])
        if qty <= 0: continue
        flt = [["item_code", "=", bal["item_code"]], ["warehouse", "=", bal["warehouse"]], ["actual_qty", ">", 0], ["posting_date", "<=", day.isoformat()]]
        receipts = sorted(get_list("Stock Ledger Record", filters=flt, fields=["posting_date", "actual_qty"], limit=100000, ignore_permissions=True), key=lambda r: str(r["posting_date"]), reverse=True)
        bands = [Decimal("0")] * 4; left = qty; oldest = 0
        for r in receipts:
            if left <= 0: break
            take = min(left, _q(r["actual_qty"])); left -= take
            d0 = r["posting_date"]; d0 = d0.date() if isinstance(d0, datetime) else (d0 if isinstance(d0, date) else date.fromisoformat(str(d0)[:10]))
            age = max(0, (day - d0).days); oldest = max(oldest, age)
            bands[0 if age <= 30 else 1 if age <= 60 else 2 if age <= 90 else 3] += take
        out.append({"item_code": bal["item_code"], "warehouse": bal["warehouse"], "on_hand": float(qty), "age_0_30": float(bands[0]), "age_31_60": float(bands[1]),
                    "age_61_90": float(bands[2]), "age_over_90": float(bands[3]), "oldest_days": oldest, "stock_value": float(_q(bal["stock_value"]))})
    return sorted(out, key=lambda r: -r["age_over_90"])
