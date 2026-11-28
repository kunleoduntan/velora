"""Sandboxed Jinja2 rendering for saved print formats.

Print formats designed in Frappe/ERPNext use ``{{ doc.field }}``, ``{% for item in doc.items %}``, ``frappe.utils.formatdate(...)``,
``frappe.format_value(...)`` and ``frappe.db.get_value(...)``. This module makes those formats render here: the document is exposed as
``doc`` (with the familiar aliases ``items``, ``taxes``, ``posting_date``, ``customer_name``, ``net_total`` ...) and a small ``frappe``
shim supplies the helpers. Templates run in Jinja's sandbox, may only read what the printing user may read, and cannot reach the
filesystem, imports or private attributes.
"""
from __future__ import annotations
import html
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from jinja2 import ChainableUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from .exceptions import ValidationError

_LINE_ALIASES = {"qty": "quantity", "item_name": "description", "batch_no": "batch", "serial_no": "serial_number",
                 "stock_uom": "uom", "net_amount": "amount", "warehouse": "warehouse"}
_DOC_ALIASES = {"posting_date": ("posting_date", "invoice_date", "document_date"), "transaction_date": ("document_date", "invoice_date"),
                "net_total": ("net_amount", "total_amount", "sub_total"), "total": ("net_amount", "total_amount"),
                "base_net_total": ("base_net_amount",), "base_grand_total": ("base_grand_total", "grand_total"),
                "total_taxes_and_charges": ("tax_amount",), "terms": ("terms", "terms_and_conditions"),
                "remarks": ("narration", "remarks"), "po_no": ("party_reference",), "conversion_rate": ("exchange_rate",),
                "outstanding_amount": ("balance_due", "outstanding_amount"), "status": ("payment_status", "approval_status", "status")}
_MISSING = object()


class Row:
    """A child-table row; unknown names render as empty instead of raising, so a format keeps printing when a field does not exist."""
    __slots__ = ("_d",)

    def __init__(self, data): object.__setattr__(self, "_d", data)
    def __getattr__(self, key):
        d = object.__getattribute__(self, "_d")
        if key in d and d[key] not in (None, ""): return d[key]
        alias = _LINE_ALIASES.get(key)
        if alias and d.get(alias) not in (None, ""): return d[alias]
        if key == "item_name": return d.get("description") or d.get("item_code") or ""
        if key == "discount_amount": return d.get("discount_amount") or 0
        return d.get(key, "")
    def get(self, key, default=None):
        v = getattr(self, key); return default if v in ("", None) else v
    def __iter__(self): return iter(object.__getattribute__(self, "_d"))
    def __bool__(self): return True


class Doc:
    __slots__ = ("_d", "_tables", "_meta", "_party")

    def __init__(self, values, meta, party_title=""):
        object.__setattr__(self, "_d", values); object.__setattr__(self, "_meta", meta); object.__setattr__(self, "_party", party_title)
        object.__setattr__(self, "_tables", [f.fieldname for f in meta.table_fields])

    def _rows(self, fieldname): return [Row(r) for r in (self._d.get(fieldname) or [])]

    def __getattr__(self, key):
        d = object.__getattribute__(self, "_d"); tables = object.__getattribute__(self, "_tables")
        if key in tables: return self._rows(key)
        if key in d and d[key] not in (None, ""): return d[key]
        if key == "items": return self._rows(tables[0]) if tables else []
        if key == "taxes": return self._taxes()
        if key in ("customer_name", "supplier_name", "party_name", "customer", "supplier"):
            return d.get(key) or (self._party if key.endswith("name") else d.get("party", "")) or ""
        if key == "discount_amount":
            return sum((Decimal(str(r.get("discount_amount") or 0)) * Decimal(str(r.get("quantity") or 1)) for r in (d.get(tables[0]) if tables else []) or []), Decimal("0"))
        if key == "company": return d.get("company") or ""
        for alt in _DOC_ALIASES.get(key, ()):
            if d.get(alt) not in (None, ""): return d[alt]
        return d.get(key, "")

    def _taxes(self):
        """Tax rows summed per tax account/rate from the lines, the shape Frappe formats expect (account_head, rate, tax_amount)."""
        d = object.__getattribute__(self, "_d"); tables = object.__getattribute__(self, "_tables"); agg = {}
        for r in (d.get(tables[0]) if tables else []) or []:
            amount = Decimal(str(r.get("tax_amount") or 0))
            if not amount: continue
            key = (r.get("tax_account") or r.get("tax_code") or "Tax", str(r.get("tax_rate") or 0))
            agg[key] = agg.get(key, Decimal("0")) + amount
        return [Row({"account_head": k[0], "description": k[0], "rate": k[1], "tax_amount": v}) for k, v in agg.items()]

    def get(self, key, default=None):
        v = getattr(self, key); return default if v in ("", None, []) else v
    def as_dict(self): return dict(object.__getattribute__(self, "_d"))
    def __bool__(self): return True


_FORMAT_TOKENS = (("yyyy", "%Y"), ("YYYY", "%Y"), ("MMMM", "%B"), ("MMM", "%b"), ("mm", "%m"), ("MM", "%m"), ("dd", "%d"), ("DD", "%d"),
                  ("yy", "%y"), ("HH", "%H"), ("hh", "%I"), ("ss", "%S"))


def _to_date(value):
    if isinstance(value, datetime): return value
    if isinstance(value, date): return datetime(value.year, value.month, value.day)
    if value in (None, ""): return None
    text = str(value)[:19].replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try: return datetime.strptime(text, fmt)
        except ValueError: continue
    return None


def formatdate(value, fmt="dd-MM-yyyy"):
    moment = _to_date(value)
    if moment is None: return "" if value in (None, "") else str(value)
    out = fmt or "dd-MM-yyyy"
    for token, code in _FORMAT_TOKENS: out = out.replace(token, code)
    return moment.strftime(out)


def _number(value):
    try: return Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError): return Decimal("0")


def flt(value, precision=None):
    n = float(_number(value)); return round(n, precision) if precision is not None else n


def cint(value):
    try: return int(_number(value))
    except (ValueError, OverflowError): return 0


def fmt_money(value, currency=None, precision=2):
    text = f"{_number(value):,.{precision}f}"
    return f"{currency} {text}" if currency else text


def format_value(value, df=None, doc=None, currency=None):
    kind = (df or {}).get("fieldtype") if isinstance(df, dict) else None
    if kind == "Currency": return fmt_money(value, None)
    if kind in ("Float", "Percent"): return f"{_number(value):,.2f}"
    if kind == "Int": return f"{cint(value):,}"
    if kind in ("Date", "Datetime") or isinstance(value, (date, datetime)): return formatdate(value)
    if isinstance(value, Decimal): return f"{value:,.2f}"
    return "" if value is None else str(value)


_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_UNITS = {"NGN": ("naira", "kobo"), "USD": ("US dollars", "cents"), "GBP": ("pounds", "pence"), "EUR": ("euros", "cents"), "GHS": ("cedis", "pesewas"), "KES": ("Kenya shillings", "cents"), "ZAR": ("rand", "cents")}


def _below_thousand(n):
    parts = []
    if n >= 100:
        parts.append(f"{_ONES[n // 100]} hundred"); n %= 100
        if n: parts.append("and")
    if n >= 20:
        parts.append(_TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else ""))
    elif n or not parts:
        parts.append(_ONES[n])
    return " ".join(parts)


def number_in_words(n: int) -> str:
    if n == 0: return "zero"
    names = ((10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (10 ** 3, "thousand"))
    out = []
    for size, label in names:
        if n >= size:
            out.append(f"{_below_thousand(n // size)} {label}"); n %= size
    if n:
        out.append(("and " if out and n < 100 else "") + _below_thousand(n))
    return " ".join(out)


def money_in_words(value, currency=None):
    """'One thousand two hundred and fifty naira, forty kobo only'. Amounts of 10^15 or more are returned as figures."""
    amount = _number(value)
    sign = "minus " if amount < 0 else ""
    amount = abs(amount).quantize(Decimal("0.01"))
    whole, minor = int(amount), int((amount - int(amount)) * 100)
    if whole >= 10 ** 15: return fmt_money(value, currency)
    major_name, minor_name = _UNITS.get((currency or "").upper(), ((currency or "").upper() or "units", "minor units"))
    text = f"{number_in_words(whole)} {major_name}" + (f", {number_in_words(minor)} {minor_name}" if minor else "")
    text = sign + text + " only"
    return text[0].upper() + text[1:]


class _Db:
    """frappe.db.get_value(doctype, name, field) limited to what the printing user may read; any failure returns None, as Frappe does."""
    def get_value(self, doctype, name=None, fieldname=None, *args, **kwargs):
        try:
            from .document.document import get_doc
            if isinstance(name, dict): return None
            doc = get_doc(doctype, name)
            if isinstance(fieldname, (list, tuple)): return tuple(getattr(doc, f, None) for f in fieldname)
            return getattr(doc, fieldname, None) if fieldname else None
        except Exception: return None
    def exists(self, doctype, name=None):
        return self.get_value(doctype, name, "name")
    def get_single_value(self, *a, **k): return None


class _Utils:
    formatdate = staticmethod(formatdate); flt = staticmethod(flt); cint = staticmethod(cint); fmt_money = staticmethod(fmt_money)
    getdate = staticmethod(lambda v=None: (_to_date(v) or datetime.now()).date())
    now_datetime = staticmethod(lambda: datetime.now())
    nowdate = staticmethod(lambda: date.today().isoformat())
    today = staticmethod(lambda: date.today().isoformat())
    escape_html = staticmethod(lambda v: html.escape("" if v is None else str(v)))
    money_in_words = staticmethod(money_in_words)
    def __getattr__(self, key): raise AttributeError(key)


class Frappe:
    db = _Db(); utils = _Utils()
    format_value = staticmethod(format_value)
    _ = staticmethod(lambda text, *a, **k: text)
    def format(self, value, df=None, doc=None): return format_value(value, df)
    def __getattr__(self, key): return lambda *a, **k: ""


_env = SandboxedEnvironment(autoescape=True, undefined=ChainableUndefined, trim_blocks=False, lstrip_blocks=False)
_env.globals.update({"frappe": Frappe(), "formatdate": formatdate, "flt": flt, "cint": cint, "fmt_money": fmt_money, "money_in_words": money_in_words, "format_value": format_value,
                     "_": lambda t, *a, **k: t, "len": len, "range": range})
_env.filters.update({"money": lambda v, cur=None: fmt_money(v, cur), "date": formatdate, "flt": flt, "int": cint})


def is_jinja(template):
    return "{%" in template or "{#" in template or "{{" in template


def validate(template):
    """Reject a template that does not compile, with the line number, before it is saved."""
    try: _env.parse(template)
    except TemplateError as ex:
        raise ValidationError(f"Print template error{' on line ' + str(ex.lineno) if getattr(ex, 'lineno', None) else ''}: {ex.message if hasattr(ex, 'message') else ex}")


def render_template(template, doc_values, meta, extra=None, party_title=""):
    doc = Doc(doc_values, meta, party_title)
    context = {k: v for k, v in doc_values.items() if isinstance(k, str) and k.isidentifier()}
    context.update(extra or {}); context["doc"] = doc
    try: return _env.from_string(template).render(**context)
    except TemplateError as ex:
        raise ValidationError(f"Print template error{' on line ' + str(ex.lineno) if getattr(ex, 'lineno', None) else ''}: {getattr(ex, 'message', ex)}")
    except Exception as ex:
        raise ValidationError(f"Print template could not be rendered: {ex}")
