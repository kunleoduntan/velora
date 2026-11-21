"""Document naming: hash | prompt | field:<f> | series:<PREFIX>.####"""
import re
import secrets
import time
from datetime import date, datetime

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from . import db
from .db.system import series
from .exceptions import MandatoryError, ValidationError
from .meta.spec import SERIES_RE


def next_in_series(prefix: str) -> int:
    """Concurrency-safe counter.

    The UPDATE takes a row lock held until commit, so two transactions can never
    receive the same number. A rolled-back insert also rolls back its increment,
    so numbers are gap-free (important for invoices and other controlled sequences).
    """
    conn = db.conn()
    for _ in range(2):
        res = conn.execute(update(series).where(series.c.name == prefix).values(current=series.c.current + 1))
        if res.rowcount:
            break
        try:
            with conn.begin_nested():
                conn.execute(insert(series).values(name=prefix, current=0))
        except IntegrityError:
            pass  # someone else created it first; loop and update
    return conn.execute(select(series.c.current).where(series.c.name == prefix)).scalar_one()


RULES_KEY = "naming.rules"
_DATE_TOKEN = re.compile(r"\.(YYYY|YY|MM|DD)\.")
_DATE_FIELDS = ("posting_date", "transaction_date", "invoice_date", "payment_date", "receipt_date", "voucher_date", "order_date", "date")
_rules_cache: tuple[float, dict] = (0.0, {})


def clear_rules_cache() -> None:
    global _rules_cache
    _rules_cache = (0.0, {})


def rules() -> dict:
    """{DocType: series pattern} configured by the company (Naming Series Rule). Cached for 30 s per process."""
    global _rules_cache
    stamp, value = _rules_cache
    if time.monotonic() - stamp < 30:
        return value
    from .settings import get_setting
    raw = get_setting(RULES_KEY, {}) or {}
    value = raw if isinstance(raw, dict) else {}
    _rules_cache = (time.monotonic(), value)
    return value


def resolve_prefix(prefix: str, when: date) -> str:
    """'INV-.YYYY.-' -> 'INV-2026-'. The counter is keyed by the RESOLVED prefix, so a year token restarts numbering each year."""
    fmt = {"YYYY": f"{when:%Y}", "YY": f"{when:%y}", "MM": f"{when:%m}", "DD": f"{when:%d}"}
    return _DATE_TOKEN.sub(lambda m: fmt[m.group(1)], prefix)


def _doc_date(doc) -> date:
    for name in _DATE_FIELDS:
        v = doc.get(name) if hasattr(doc, "get") else getattr(doc, name, None)
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        if isinstance(v, str) and len(v) >= 10:
            try:
                return date.fromisoformat(v[:10])
            except ValueError:
                pass
    return date.today()


def make_name(meta, doc) -> str:
    spec = meta.autoname
    override = None if meta.istable else rules().get(meta.name)
    if override:
        spec = f"series:{override}"
    if meta.istable or spec in (None, "hash"):
        return secrets.token_hex(5)
    if spec == "prompt":
        if not doc.name:
            raise MandatoryError(f"{meta.name}: a name is required")
        return str(doc.name).strip()
    if spec.startswith("field:"):
        value = doc.get(spec[6:])
        if value in (None, ""):
            raise MandatoryError(f"{meta.name}: {spec[6:]} is required")
        return str(value).strip()
    m = SERIES_RE.match(spec)
    if not m:
        raise ValidationError(f"Bad autoname {spec!r}")
    prefix, width = resolve_prefix(m.group("prefix"), _doc_date(doc)), len(m.group("hashes"))
    return f"{prefix}{next_in_series(prefix):0{width}d}"
