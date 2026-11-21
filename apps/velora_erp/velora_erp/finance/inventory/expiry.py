"""Batch expiry: what is about to expire, what already has, and keeping expired stock from being sold or sent on."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from velora import db, get_doc, throw
from velora.db.tables import get_table


def alert_days() -> int:
    from velora_erp.finance.inventory.controls import controls
    return int(controls()["expiry_alert_days"])


def blocking() -> bool:
    from velora_erp.finance.inventory.controls import controls
    return bool(controls()["block_issue_of_expired_batches"])


def batch_rows(days: int | None = None, warehouse: str | None = None, item_code: str | None = None, as_of: date | None = None, include_ok: bool = False) -> list[dict]:
    """Batches that still have stock, with days left to expiry. By default only the expired and those expiring within `days`."""
    today = as_of or date.today()
    horizon = today + timedelta(days=alert_days() if days is None else int(days))
    led, bt = get_table("Stock Ledger Record"), get_table("Batch")
    cond = [led.c.batch.isnot(None)]
    if warehouse: cond.append(led.c.warehouse == warehouse)
    if item_code: cond.append(led.c.item_code == item_code)
    with db.transaction() as c:
        stock = c.execute(select(led.c.item_code, led.c.batch, led.c.warehouse, func.sum(led.c.actual_qty), func.sum(led.c.stock_value_difference))
                          .where(*cond).group_by(led.c.item_code, led.c.batch, led.c.warehouse)).all()
        dates = {r[0]: r[1] for r in c.execute(select(bt.c.name, bt.c.expiry_date)).all()}
    out = []
    for item, batch, wh, qty, value in stock:
        qty = Decimal(str(qty or 0))
        expiry = dates.get(batch)
        if qty <= 0 or expiry is None:
            continue
        left = (expiry - today).days
        status = "Expired" if left < 0 else ("Expiring soon" if expiry <= horizon else "OK")
        if status == "OK" and not include_ok:
            continue
        out.append({"item_code": item, "batch": batch, "warehouse": wh, "quantity": float(qty), "stock_value": float(value or 0),
                    "expiry_date": expiry, "days_left": left, "status": status})
    return sorted(out, key=lambda r: (r["expiry_date"], r["item_code"], r["warehouse"]))


def assert_not_expired(source, item_code: str, batch: str | None, *, to_warehouse: str | None = None) -> None:
    """Block delivering or transferring an expired batch. Moving it to a quarantine warehouse, or scrapping it with a stock entry, stays possible."""
    if not batch or not blocking():
        return
    kind = source.doctype
    if kind in ("Delivery Note", "Sales Invoice"):
        pass
    elif kind == "Stock Transfer":
        final = getattr(source, "target_warehouse", None) or to_warehouse
        if final and get_doc("Warehouse", final).is_quarantine_warehouse:
            return
    else:
        return
    expiry = get_doc("Batch", batch).expiry_date
    posted = getattr(source, "posting_date", None) or getattr(source, "document_date", None) or date.today()
    if expiry and expiry < posted:
        throw(f"Batch {batch} of {item_code} expired on {expiry}. It cannot be delivered or moved to a normal warehouse; "
              f"transfer it to a quarantine warehouse or scrap it with a stock entry.")


def watch_expiry() -> int:
    """Daily task: tell the Notification Centre about stock that is expired or about to expire (rule event `batch_expiring`), once per batch per day."""
    try:
        from velora_notify import engine
    except Exception:  # noqa: BLE001 - notifications are optional
        return 0
    sent = 0
    for row in batch_rows():
        doc = get_doc("Batch", row["batch"], ignore_permissions=True)
        try:
            sent += engine.trigger("batch_expiring", doc, key=f"{row['batch']}:{row['warehouse']}:{date.today()}")
        except Exception:  # noqa: BLE001 - the Notification Centre is not set up on this site
            return sent
    return sent
