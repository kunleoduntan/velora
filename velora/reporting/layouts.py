"""Financial report layouts: reusable row and column definitions inspired by Business Central.

A layout is metadata, not a hard-coded statement. Rows define account filters, formulas,
indentation and presentation. Columns define period calculations and comparative periods.
The execution adapter accepts account balances supplied by the accounting/ledger layer.
"""
from __future__ import annotations

import json
import re
import secrets
from decimal import Decimal, InvalidOperation
from datetime import date
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, delete, insert, select, update

from .. import db
from ..document.document import now
from ..exceptions import DoesNotExistError, PermissionDenied, ValidationError
from ..permissions import get_session

md = MetaData()
_layout = Table("vl_financial_report_layout", md,
    Column("id", String(24), primary_key=True),
    Column("name", String(100), nullable=False),
    Column("owner", String(254), nullable=False),
    Column("shared", Integer, nullable=False, default=0),
    Column("definition", JSON, nullable=False),
    Column("created_on", DateTime), Column("updated_on", DateTime))

ROW_TYPES = {"account", "account_range", "account_category", "formula", "text", "blank", "dimension"}
COLUMN_TYPES = {"net_change", "balance_at_date", "period_to_date", "year_to_date", "same_period_last_year", "opening_balance", "budget", "formula", "text", "blank"}
OPS = {"+", "-", "*", "/", "(", ")"}
IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
MAX_ROWS, MAX_COLUMNS = 500, 60


def _manager():
    s = get_session()
    return s.user == "Administrator" or "System Manager" in s.roles


def _ensure():
    from ..db.extra_tables import ensure
    ensure(md)


def _name(value):
    value = str(value or "").strip()
    if not value or len(value) > 100 or any(ord(c) < 32 for c in value):
        raise ValidationError("Layout name must contain 1-100 printable characters")
    return value


def validate_definition(value):
    if not isinstance(value, dict):
        raise ValidationError("Financial report definition must be an object")
    if len(json.dumps(value, default=str)) > 100_000:
        raise ValidationError("Financial report definition is too large")
    rows, cols = value.get("rows"), value.get("columns")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ROWS:
        raise ValidationError(f"Define between 1 and {MAX_ROWS} report rows")
    if not isinstance(cols, list) or not cols or len(cols) > MAX_COLUMNS:
        raise ValidationError(f"Define between 1 and {MAX_COLUMNS} report columns")
    seen = set()
    clean_rows = []
    for i, raw in enumerate(rows, 1):
        if not isinstance(raw, dict): raise ValidationError(f"Row {i} must be an object")
        code = str(raw.get("code") or "").strip()
        kind = raw.get("type", "account")
        if not IDENT.match(code) or code in seen: raise ValidationError(f"Row {i}: code must be unique and use letters, numbers and underscores")
        seen.add(code)
        if kind not in ROW_TYPES: raise ValidationError(f"Row {code}: unsupported row type {kind!r}")
        row = {"code": code, "description": str(raw.get("description") or code)[:160], "type": kind,
               "indent": int(raw.get("indent", 0)), "bold": bool(raw.get("bold", False)),
               "italic": bool(raw.get("italic", False)), "show": bool(raw.get("show", True))}
        if not 0 <= row["indent"] <= 10: raise ValidationError(f"Row {code}: indent must be 0-10")
        if kind in {"account", "account_range", "account_category", "dimension"}:
            if kind == "account" and not raw.get("account_no"): raise ValidationError(f"Row {code}: account_no is required")
            if kind == "account_range" and (not raw.get("from_account") or not raw.get("to_account")): raise ValidationError(f"Row {code}: from_account and to_account are required")
            if kind == "account_category" and not raw.get("category"): raise ValidationError(f"Row {code}: category is required")
            if kind == "dimension" and not raw.get("dimension"): raise ValidationError(f"Row {code}: dimension is required")
            for key in ("account_no", "from_account", "to_account", "category", "dimension", "dimension_value", "sign"):
                if key in raw: row[key] = raw[key]
            row["sign"] = int(row.get("sign", 1))
            if row["sign"] not in (-1, 1): raise ValidationError(f"Row {code}: sign must be -1 or 1")
        if kind == "formula":
            formula = str(raw.get("formula") or "").strip()
            refs = re.findall(r"\[([A-Za-z][A-Za-z0-9_]*)\]", formula)
            if not formula or not refs: raise ValidationError(f"Row {code}: formula must reference at least one row using [ROW_CODE]")
            if not re.fullmatch(r"[A-Za-z0-9_+*/().\[\] \-]+", formula) or "**" in formula or len(formula) > MAX_FORMULA_LENGTH: raise ValidationError(f"Row {code}: formula may only use + - * / and parentheses (no powers) and must be under {MAX_FORMULA_LENGTH} characters")
            row["formula"] = formula
        if kind == "text": row["text"] = str(raw.get("text") or row["description"])[:500]
        clean_rows.append(row)
    prior_codes = set()
    for row in clean_rows:
        if row["type"] == "formula":
            refs = re.findall(r"\[([A-Za-z][A-Za-z0-9_]*)\]", row["formula"])
            missing = set(refs) - seen
            if missing: raise ValidationError(f"Row {row['code']}: unknown row reference(s): {', '.join(sorted(missing))}")
            forward = set(refs) - prior_codes
            if forward: raise ValidationError(f"Row {row['code']}: formulas may reference only rows defined above: {', '.join(sorted(forward))}")
        prior_codes.add(row["code"])
    seen_cols, clean_cols = set(), []
    for i, raw in enumerate(cols, 1):
        if not isinstance(raw, dict): raise ValidationError(f"Column {i} must be an object")
        code = str(raw.get("code") or "").strip()
        kind = raw.get("type", "net_change")
        if not IDENT.match(code) or code in seen_cols: raise ValidationError(f"Column {i}: code must be unique and use letters, numbers and underscores")
        seen_cols.add(code)
        if kind not in COLUMN_TYPES: raise ValidationError(f"Column {code}: unsupported type {kind!r}")
        col = {"code": code, "caption": str(raw.get("caption") or code)[:100], "type": kind,
               "date_mode": raw.get("date_mode", "current_period"), "period": raw.get("period", "month"),
               "offset": int(raw.get("offset", 0)), "width": int(raw.get("width", 16))}
        if col["date_mode"] not in {"current_period", "custom", "as_of"}: raise ValidationError(f"Column {code}: invalid date_mode")
        if col["period"] not in {"day", "week", "month", "quarter", "year", "accounting_period"}: raise ValidationError(f"Column {code}: invalid period")
        if not -120 <= col["offset"] <= 120: raise ValidationError(f"Column {code}: offset must be -120 to 120")
        if not 6 <= col["width"] <= 60: raise ValidationError(f"Column {code}: width must be 6-60")
        if kind == "formula":
            formula = str(raw.get("formula") or "").strip()
            refs = re.findall(r"\[([A-Za-z][A-Za-z0-9_]*)\]", formula)
            if "**" in formula or len(formula) > MAX_FORMULA_LENGTH:
                raise ValidationError(f"Column {code}: formula may only use + - * / and parentheses, and must be shorter than {MAX_FORMULA_LENGTH} characters")
            if not formula or not refs or not re.fullmatch(r"[A-Za-z0-9_+*/().\[\] \-]+", formula):
                raise ValidationError(f"Column {code}: formula must reference columns using [COLUMN_CODE]")
            col["formula"] = formula
        if kind == "text": col["text"] = str(raw.get("text") or "")[:500]
        clean_cols.append(col)
    prior_columns = set()
    for col in clean_cols:
        if col["type"] == "formula":
            refs = set(re.findall(r"\[([A-Za-z][A-Za-z0-9_]*)\]", col["formula"]))
            missing = refs - seen_cols
            if missing: raise ValidationError(f"Column {col['code']}: unknown column reference(s): {', '.join(sorted(missing))}")
            forward = refs - prior_columns
            if forward: raise ValidationError(f"Column {col['code']}: formulas may reference only columns defined to the left: {', '.join(sorted(forward))}")
        prior_columns.add(col["code"])
    return {"rows": clean_rows, "columns": clean_cols, "options": value.get("options", {}) if isinstance(value.get("options", {}), dict) else {}}


MAX_FORMULA_LENGTH = 1000
MAX_FORMULA_DEPTH = 250


def _arithmetic(expr: str) -> Decimal:
    """Evaluate safe arithmetic using Decimal so report formulas do not introduce binary-float drift."""
    import ast
    import operator
    if len(expr) > MAX_FORMULA_LENGTH:
        raise ValidationError("Formula is too long")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise ValidationError("Invalid formula expression") from exc
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul}

    def walk(node, depth=0):
        if depth > MAX_FORMULA_DEPTH:
            raise ValidationError("Formula is nested too deeply")
        if isinstance(node, ast.Expression):
            return walk(node.body, depth + 1)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = walk(node.operand, depth + 1)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Div):
                right = walk(node.right, depth + 1)
                left = walk(node.left, depth + 1)
                if right == 0:
                    raise ZeroDivisionError
                return left / right
            if type(node.op) in ops:
                return ops[type(node.op)](walk(node.left, depth + 1), walk(node.right, depth + 1))
        raise ValidationError("Invalid formula expression")
    return walk(tree)


def _eval_formula(formula, values):
    def as_decimal(value):
        try:
            return str(Decimal(str(value if value not in (None, "") else 0)))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError("A report formula references a non-numeric value")
    expr = re.sub(r"\[([A-Za-z][A-Za-z0-9_]*)\]", lambda m: as_decimal(values.get(m.group(1), 0)), formula)
    if not re.fullmatch(r"[0-9eE.+*/() \-]+", expr): raise ValidationError("Invalid formula expression")
    try: return _arithmetic(expr)
    except ZeroDivisionError: return 0
    except ValidationError: raise
    except (OverflowError, RecursionError, MemoryError, ValueError) as exc: raise ValidationError("Could not evaluate report formula") from exc


def calculate(definition, balances, periods, account_attributes=None):
    """Calculate a report matrix.

    balances maps (account_no, column_code) -> numeric balance. `periods` maps column
    codes to display labels. The caller must apply ledger/company/permission filters before
    supplying balances; this module never queries ledger tables directly.
    """
    spec = validate_definition(definition)
    account_attributes = account_attributes or {}
    row_values = {}
    for row in spec["rows"]:
        vals = {}
        for col in spec["columns"]:
            if row["type"] in {"account", "account_range", "account_category", "dimension"}:
                total = Decimal("0")
                for (acct, ccode), amount in balances.items():
                    if ccode != col["code"]: continue
                    attrs = account_attributes.get(acct, {}) or {}
                    match = (row["type"] == "account" and acct == row["account_no"]) or (row["type"] == "account_range" and str(row["from_account"]) <= str(acct) <= str(row["to_account"]))
                    if row["type"] == "account_category":
                        match = attrs.get("category") == row.get("category")
                    if row["type"] == "dimension":
                        dimensions = attrs.get("dimensions", {}) or {}
                        match = dimensions.get(row.get("dimension")) == row.get("dimension_value")
                    if match: total += Decimal(str(amount or 0))
                vals[col["code"]] = total * row.get("sign", 1)
            elif row["type"] == "formula": vals[col["code"]] = _eval_formula(row["formula"], {r: row_values.get(r, {}).get(col["code"], 0) for r in re.findall(r"\[([A-Za-z][A-Za-z0-9_]*)\]", row["formula"])})
            else: vals[col["code"]] = None
        row_values[row["code"]] = vals
    # Column formulas are evaluated for each report row after base period columns exist.
    for row in spec["rows"]:
        for col in spec["columns"]:
            if col["type"] == "formula":
                row_values[row["code"]][col["code"]] = _eval_formula(col["formula"], row_values[row["code"]])
    return {"columns": [{"code": c["code"], "caption": c["caption"], "type": c["type"], "period_label": periods.get(c["code"], c["caption"]), "width": c["width"]} for c in spec["columns"]],
            "rows": [{"code": r["code"], "description": r["description"], "type": r["type"], "indent": r["indent"], "bold": r["bold"], "italic": r["italic"], "values": row_values[r["code"]]} for r in spec["rows"] if r["show"]]}


def list_layouts():
    _ensure()
    with db.transaction() as conn: rows = conn.execute(select(_layout).order_by(_layout.c.name)).mappings().all()
    return [{"id": r["id"], "name": r["name"], "shared": bool(r["shared"]), "can_edit": r["owner"] == get_session().user or _manager(), "definition": r["definition"]} for r in rows if r["owner"] == get_session().user or r["shared"]]


def get_layout(lid):
    _ensure()
    with db.transaction() as conn: r = conn.execute(select(_layout).where(_layout.c.id == lid)).mappings().first()
    if not r or (r["owner"] != get_session().user and not r["shared"]): raise DoesNotExistError("Financial report layout not found")
    return {"id": r["id"], "name": r["name"], "shared": bool(r["shared"]), "can_edit": r["owner"] == get_session().user or _manager(), "definition": r["definition"]}


def save_layout(name, definition, lid=None, shared=False):
    name, definition = _name(name), validate_definition(definition)
    if shared and not _manager(): raise PermissionDenied("Only a System Manager can share a financial report layout")
    _ensure()
    with db.transaction() as conn:
        if lid:
            r = conn.execute(select(_layout).where(_layout.c.id == lid)).mappings().first()
            if not r or (r["owner"] != get_session().user and not _manager()): raise PermissionDenied("Only the owner or a System Manager can edit this layout")
            conn.execute(update(_layout).where(_layout.c.id == lid).values(name=name, definition=definition, shared=bool(shared), updated_on=now()))
        else:
            lid = "FR-" + secrets.token_hex(8)
            conn.execute(insert(_layout).values(id=lid, name=name, owner=get_session().user, definition=definition, shared=bool(shared), created_on=now(), updated_on=now()))
    return get_layout(lid)


def delete_layout(lid):
    cur = get_layout(lid)
    if not cur["can_edit"]: raise PermissionDenied("Only the owner or a System Manager can delete this layout")
    with db.transaction() as conn: conn.execute(delete(_layout).where(_layout.c.id == lid))
    return {"deleted": lid}


# ---- Financial statement execution and ledger drill-down ---------------------------------------
def _period_bounds(column, filters):
    """Resolve a report column to a concrete date window without discarding user date filters."""
    from datetime import date, timedelta
    start = date.fromisoformat(str(filters.get("from_date"))) if filters.get("from_date") else date.today().replace(day=1)
    end = date.fromisoformat(str(filters.get("to_date"))) if filters.get("to_date") else date.today()
    mode, unit, offset = column.get("date_mode", "current_period"), column.get("period", "month"), int(column.get("offset", 0))
    if column.get("type") == "opening_balance":
        from datetime import timedelta
        end = start - timedelta(days=1)
        start = end
    elif mode == "as_of":
        as_at = date.fromisoformat(str(filters.get("as_of_date") or filters.get("to_date") or date.today().isoformat()))
        if offset:
            as_at = _shift_date(as_at, offset, unit)
        if unit == "year":
            start = date(as_at.year, 1, 1)
        elif unit == "quarter":
            start = date(as_at.year, ((as_at.month - 1) // 3) * 3 + 1, 1)
        else:
            start = date(as_at.year, as_at.month, 1)
        end = as_at
    elif column.get("type") == "year_to_date":
        shifted_end = _shift_date(end, offset, "year")
        start, end = date(shifted_end.year, 1, 1), shifted_end
    elif column.get("type") == "period_to_date":
        shifted_end = _shift_date(end, offset, unit)
        if unit == "year": start = date(shifted_end.year, 1, 1)
        elif unit == "quarter": start = date(shifted_end.year, ((shifted_end.month - 1) // 3) * 3 + 1, 1)
        elif unit == "week": start = shifted_end - timedelta(days=shifted_end.weekday())
        else: start = date(shifted_end.year, shifted_end.month, 1)
        end = shifted_end
    elif mode == "current_period" and offset:
        start, end = _shift_date(start, offset, unit), _shift_date(end, offset, unit)
    return start, end


def _shift_date(value, offset, unit):
    from datetime import date, timedelta
    if unit in {"month", "quarter", "year"}:
        import calendar
        months = offset * ({"month": 1, "quarter": 3, "year": 12}[unit])
        index = value.year * 12 + value.month - 1 + months
        year, month0 = divmod(index, 12)
        month = month0 + 1
        return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))
    if unit == "week": return value + timedelta(weeks=offset)
    if unit == "day": return value + timedelta(days=offset)
    return value


def _financial_reporting_provider():
    """Resolve the single installed app that owns the authoritative financial ledger."""
    from .financial_provider import resolve_financial_reporting_provider
    return resolve_financial_reporting_provider()


def _accounting_tables():
    """Return legacy accounting tables only when no app-level reporting adapter exists."""
    try:
        from ..db.tables import get_table
        return get_table("Account"), get_table("GL Entry")
    except Exception as exc:
        raise ValidationError("Financial statement execution requires an installed financial reporting provider or the legacy Accounts app.") from exc


def _check_financial_read():
    provider = _financial_reporting_provider()
    if provider is not None:
        required = ("check_access", "get_accounts", "get_account_totals", "get_ledger_entries")
        missing = [name for name in required if not callable(getattr(provider, name, None))]
        if missing:
            raise ValidationError(f"Financial reporting provider is missing required function(s): {', '.join(missing)}")
        provider.check_access()
        return provider
    from .. import registry
    from ..permissions import check_permission
    check_permission(registry.get("Account"), "read")
    check_permission(registry.get("GL Entry"), "read")
    from ..permissions import field_access
    required = {
        "Account": ("name", "account_number", "root_type", "is_group", "disabled"),
        "GL Entry": ("name", "posting_date", "account", "debit", "credit", "voucher_type", "voucher_no", "party_type", "party", "remarks", "is_cancelled", "is_reversal"),
    }
    for doctype, fields in required.items():
        hidden = [field for field in fields if field_access(doctype, field) == "hidden"]
        if hidden:
            from ..exceptions import PermissionDenied
            raise PermissionDenied(f"Financial reporting requires read access to {doctype} field(s): {', '.join(hidden)}")
    return None


def _row_account_predicate(row, account_table):
    from sqlalchemy import and_
    kind = row["type"]
    if kind == "account":
        return account_table.c.name == row["account_no"]
    if kind == "account_range":
        # Account numbers are preferred; account names are the fallback key in charts without numbering.
        key = account_table.c.account_number
        return and_(key >= str(row["from_account"]), key <= str(row["to_account"]))
    if kind == "account_category":
        return account_table.c.root_type == row["category"]
    if kind == "dimension":
        raise ValidationError("Dimension-based statement execution requires a dimension mapping adapter; no unsafe implicit join is performed.")
    return None


def _normalise_report_dimensions(filters):
    """Validate supported ledger dimensions; never accept caller-supplied SQL field names."""
    allowed = {"cost_centre", "branch", "business_unit", "project", "department"}
    result = {}
    for key in allowed:
        value = filters.get(key)
        if value not in (None, ""):
            value = str(value).strip()
            if not value or len(value) > 140 or any(ord(ch) < 32 for ch in value):
                raise ValidationError(f"Invalid {key.replace('_', ' ').title()} report filter")
            result[key] = value
    return result


def _provider_totals(provider, accounts, start, end, balance_at_date, dimensions):
    import inspect
    method = provider.get_account_totals
    if dimensions and "dimensions" not in inspect.signature(method).parameters:
        raise ValidationError("The installed financial reporting provider does not support dimension filters.")
    return method(accounts, start, end, balance_at_date=balance_at_date, **({"dimensions": dimensions} if "dimensions" in inspect.signature(method).parameters else {}))


def _provider_entries(provider, accounts, start, end, limit, balance_at_date, dimensions):
    import inspect
    method = provider.get_ledger_entries
    if dimensions and "dimensions" not in inspect.signature(method).parameters:
        raise ValidationError("The installed financial reporting provider does not support dimension filters.")
    return method(accounts, start, end, limit, balance_at_date=balance_at_date, **({"dimensions": dimensions} if "dimensions" in inspect.signature(method).parameters else {}))


def execute_statement(definition, filters):
    """Run a saved layout against the active company's GL. The selected site database is the isolation boundary."""
    from sqlalchemy import select, func, and_
    from .. import db
    from ..db.tables import get_table
    provider = _check_financial_read()
    spec = validate_definition(definition)
    has_budget = any(c["type"] == "budget" for c in spec["columns"])
    if not isinstance(filters, dict):
        raise ValidationError("Report filters must be an object")
    start = date.fromisoformat(str(filters.get("from_date"))) if filters.get("from_date") else date.today().replace(day=1)
    end = date.fromisoformat(str(filters.get("to_date"))) if filters.get("to_date") else date.today()
    if start > end:
        raise ValidationError("From date cannot be after To date")
    dimensions = _normalise_report_dimensions(filters)
    budget_name = str(filters.get("budget_name") or "").strip()
    if has_budget and not budget_name:
        raise ValidationError("Select a Budget Name before running a budget-versus-actual report.")
    if has_budget and provider is None:
        raise ValidationError("Budget reporting requires an installed financial reporting provider with an approved budget adapter.")
    if dimensions and provider is None:
        raise ValidationError("The installed accounting provider does not support dimension-aware financial reporting.")
    if any(r["type"] == "dimension" for r in spec["rows"]) and provider is None:
        raise ValidationError("Dimension rows require a dimension-aware financial reporting provider.")
    accounts, gl = (None, None) if provider else _accounting_tables()
    # The selected provider performs permission checks and returns canonical account/ledger fields.
    with db.transaction() as conn:
        account_rows = provider.get_accounts() if provider else conn.execute(select(accounts.c.name, accounts.c.account_number, accounts.c.root_type, accounts.c.is_group, accounts.c.disabled)).mappings().all()
        account_rows = [dict(r) for r in account_rows]
        account_by_name = {r["name"]: dict(r) for r in account_rows}
        balances, labels, row_accounts, raw_periods = {}, {}, {}, {}
        for col in spec["columns"]:
            if col["type"] in {"formula", "text", "blank"}:
                labels[col["code"]] = col.get("caption", col["code"])
                continue
            cstart, cend = _period_bounds(col, filters)
            labels[col["code"]] = f"{cstart.isoformat()} to {cend.isoformat()}"
            raw_periods[col["code"]] = (cstart, cend)
            for row in spec["rows"]:
                if row["type"] not in {"account", "account_range", "account_category", "dimension"}:
                    continue
                if row["type"] == "dimension":
                    matched = [a["name"] for a in account_rows if not a["is_group"] and not a["disabled"]]
                    row_dimensions = dict(dimensions)
                    key, value = str(row.get("dimension") or ""), str(row.get("dimension_value") or "")
                    if key not in {"cost_centre", "branch", "business_unit", "project", "department"} or not value:
                        raise ValidationError(f"Dimension row {row['code']} must use a supported dimension and a dimension value.")
                    if key in row_dimensions and row_dimensions[key] != value:
                        row_dimensions[key] = "__NO_MATCH__"
                    else:
                        row_dimensions[key] = value
                else:
                    row_dimensions = dimensions
                    matched = [a["name"] for a in account_rows if not a["is_group"] and not a["disabled"] and (
                        (row["type"] == "account" and a["name"] == row["account_no"]) or
                        (row["type"] == "account_range" and a["account_number"] is not None and str(row["from_account"]) <= str(a["account_number"]) <= str(row["to_account"])) or
                        (row["type"] == "account_category" and a["root_type"] == row["category"])
                    )]
                row_accounts[(row["code"], col["code"])] = matched
                if not matched: balances[(row.get("account_no", row["code"]), col["code"])] = 0
                if col["type"] == "budget":
                    budget_method = getattr(provider, "get_budget_totals", None)
                    if not callable(budget_method):
                        raise ValidationError("The installed financial reporting provider does not expose approved budget totals.")
                    budget_rows = budget_method(matched, cstart, cend, budget_name=budget_name, dimensions=row_dimensions)
                    net = sum((Decimal(str(item.get("budget_amount") or 0)) for item in budget_rows), Decimal("0"))
                    balances[(row["code"], col["code"])] = net * row.get("sign", 1)
                    continue
                if provider:
                    sums = _provider_totals(provider, matched, cstart, cend, col["type"] in {"balance_at_date", "opening_balance"}, row_dimensions)
                elif col["type"] in {"balance_at_date", "opening_balance"}:
                    q = select(gl.c.account, func.coalesce(func.sum(gl.c.debit), 0).label("debit"), func.coalesce(func.sum(gl.c.credit), 0).label("credit")).where(
                        gl.c.account.in_(matched) if matched else gl.c.account == "__none__",
                        gl.c.posting_date <= cend, func.coalesce(gl.c.is_cancelled, 0) == 0).group_by(gl.c.account)
                    sums = conn.execute(q).mappings().all()
                else:
                    q = select(gl.c.account, func.coalesce(func.sum(gl.c.debit), 0).label("debit"), func.coalesce(func.sum(gl.c.credit), 0).label("credit")).where(
                        gl.c.account.in_(matched) if matched else gl.c.account == "__none__",
                        gl.c.posting_date >= cstart, gl.c.posting_date <= cend, func.coalesce(gl.c.is_cancelled, 0) == 0).group_by(gl.c.account)
                    sums = conn.execute(q).mappings().all()
                # Natural presentation: debit-positive for assets/expenses; credit-positive for liabilities/equity/income.
                root_by_name = {a["name"]: a["root_type"] for a in account_rows}
                net = Decimal("0")
                for item in sums:
                    debit, credit = Decimal(str(item["debit"] or 0)), Decimal(str(item["credit"] or 0))
                    root = root_by_name.get(item["account"])
                    amount = debit - credit if root in {"Asset", "Expense"} else credit - debit
                    net += amount
                balances[(row["code"], col["code"])] = net * row.get("sign", 1)
        # The calculation engine expects account-level balances, so feed the already permission-scoped row totals
        # through synthetic account keys and account rows. This preserves the established formula/sign engine.
        synthetic = {}
        synthetic_attrs = {}
        for (rcode, ccode), amount in balances.items():
            synthetic[(rcode, ccode)] = amount
        # A compact calculation adapter handles the row totals while retaining formula and column formula semantics.
        values = {}
        for row in spec["rows"]:
            values[row["code"]] = {}
            for col in spec["columns"]:
                if row["type"] == "formula":
                    values[row["code"]][col["code"]] = _eval_formula(row["formula"], {ref: values.get(ref, {}).get(col["code"], 0) for ref in re.findall(r"\[([A-Za-z][A-Za-z0-9_]*)\]", row["formula"])})
                elif row["type"] in {"account", "account_range", "account_category", "dimension"}:
                    values[row["code"]][col["code"]] = balances.get((row["code"], col["code"]), 0)
                else:
                    values[row["code"]][col["code"]] = None
        for row in spec["rows"]:
            for col in spec["columns"]:
                if col["type"] == "formula":
                    values[row["code"]][col["code"]] = _eval_formula(col["formula"], values[row["code"]])
        output_rows = []
        for row in spec["rows"]:
            if row["show"]:
                output_values = {key: (float(value) if isinstance(value, Decimal) else value) for key, value in values[row["code"]].items()}
                output_rows.append({"code": row["code"], "description": row["description"], "type": row["type"], "indent": row["indent"], "bold": row["bold"], "italic": row["italic"], "values": output_values})
        context = provider.get_reporting_context() if provider and callable(getattr(provider, "get_reporting_context", None)) else {}
        return {"name": str(filters.get("report_name") or "Financial Statement"), "base_currency": context.get("base_currency"), "filters": {"from_date": start.isoformat(), "to_date": end.isoformat(), "as_of_date": filters.get("as_of_date"), "budget_name": budget_name or None, **dimensions}, "columns": [{"code": c["code"], "caption": c["caption"], "type": c["type"], "period_label": labels.get(c["code"], c["caption"]), "width": c["width"]} for c in spec["columns"]], "rows": output_rows}


def statement_drilldown(definition, filters, row_code, column_code, limit=500, account_filter=None):
    """Return transaction-level GL evidence for a single account-backed statement cell."""
    from sqlalchemy import select, func
    from .. import db
    provider = _check_financial_read()
    spec = validate_definition(definition)
    row = next((r for r in spec["rows"] if r["code"] == row_code), None)
    col = next((c for c in spec["columns"] if c["code"] == column_code), None)
    if not row or not col:
        raise DoesNotExistError("Financial report row or column not found")
    if row["type"] not in {"account", "account_range", "account_category", "dimension"} or col["type"] in {"formula", "text", "blank", "budget"}:
        raise ValidationError("This statement cell has no transaction-level ledger drill-down.")
    dimensions = _normalise_report_dimensions(filters)
    if row["type"] == "dimension":
        key, value = str(row.get("dimension") or ""), str(row.get("dimension_value") or "")
        if key not in {"cost_centre", "branch", "business_unit", "project", "department"} or not value:
            raise ValidationError("The selected dimension row is not configured correctly.")
        if key in dimensions and dimensions[key] != value:
            raise ValidationError("The selected dimension row conflicts with the report filter.")
        dimensions[key] = value
    accounts, gl = (None, None) if provider else _accounting_tables()
    cstart, cend = _period_bounds(col, filters)
    with db.transaction() as conn:
        account_rows = provider.get_accounts() if provider else conn.execute(select(accounts.c.name, accounts.c.account_number, accounts.c.root_type, accounts.c.is_group, accounts.c.disabled)).mappings().all()
        account_rows = [dict(a) for a in account_rows]
        matched = [a for a in account_rows if not a["is_group"] and not a["disabled"] and (
            (row["type"] == "account" and a["name"] == row["account_no"]) or
            (row["type"] == "account_range" and a["account_number"] is not None and str(row["from_account"]) <= str(a["account_number"]) <= str(row["to_account"])) or
            (row["type"] == "account_category" and a["root_type"] == row["category"])
        )]
        names = [a["name"] for a in matched]
        if account_filter:
            if account_filter not in names:
                raise ValidationError("The selected account is not part of this statement row.")
            names = [account_filter]
        if provider:
            entries = _provider_entries(provider, names, cstart, cend, min(max(int(limit), 1), 1000), col["type"] in {"balance_at_date", "opening_balance"}, dimensions)
        else:
            q = select(gl).where(gl.c.account.in_(names) if names else gl.c.account == "__none__", gl.c.posting_date <= cend, func.coalesce(gl.c.is_cancelled, 0) == 0).order_by(gl.c.posting_date, gl.c.creation, gl.c.name).limit(min(max(int(limit), 1), 1000))
            if col["type"] not in {"balance_at_date", "opening_balance"}:
                q = q.where(gl.c.posting_date >= cstart)
            entries = [dict(x) for x in conn.execute(q).mappings().all()]
        root_map = {a["name"]: a["root_type"] for a in matched}
        details = []
        for e in entries:
            root = root_map.get(e["account"])
            debit, credit = float(e["debit"] or 0), float(e["credit"] or 0)
            amount = debit - credit if root in {"Asset", "Expense"} else credit - debit
            details.append({"name": e["name"], "posting_date": e["posting_date"].isoformat(), "account": e["account"], "voucher_type": e["voucher_type"], "voucher_no": e["voucher_no"], "party_type": e["party_type"], "party": e["party"], "remarks": e["remarks"], "debit": debit, "credit": credit, "amount": amount * row.get("sign", 1), "is_reversal": bool(e.get("is_reversal"))})
        return {"row": row_code, "description": row["description"], "column": column_code, "period_label": f"{cstart.isoformat()} to {cend.isoformat()}", "accounts": names, "entries": details, "truncated": len(details) >= min(max(int(limit), 1), 1000)}


def financial_statement_xlsx(result):
    """Create a presentation-ready, formula-safe workbook from an authorized statement result."""
    import io
    import xlsxwriter
    from datetime import datetime, timezone
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_properties({
        "title": str(result.get("name", "Financial Statement")),
        "subject": "VeloraERP financial statement generated from posted ledger records",
        "author": "VeloraERP",
        "comments": "Values are generated from the active legal entity's authoritative account ledger.",
    })
    sheet = workbook.add_worksheet("Financial Statement")
    info = workbook.add_worksheet("Report Information")
    title = workbook.add_format({"bold": True, "font_size": 17, "font_color": "#17365D", "bottom": 2, "bottom_color": "#4472C4"})
    subtitle = workbook.add_format({"font_size": 9, "font_color": "#5B6573"})
    header = workbook.add_format({"bold": True, "bg_color": "#17365D", "font_color": "#FFFFFF", "border": 1, "text_wrap": True, "valign": "vcenter"})
    label = workbook.add_format({"text_wrap": True, "valign": "vcenter"})
    number = workbook.add_format({"num_format": "#,##0.00;[Red](#,##0.00);-", "align": "right"})
    bold_number = workbook.add_format({"num_format": "#,##0.00;[Red](#,##0.00);-", "align": "right", "bold": True, "top": 1, "top_color": "#8FA3B8"})
    bold_label = workbook.add_format({"bold": True, "top": 1, "top_color": "#8FA3B8", "text_wrap": True})
    italic_label = workbook.add_format({"italic": True, "text_wrap": True})
    metadata_label = workbook.add_format({"bold": True, "font_color": "#17365D", "bg_color": "#EEF3F8", "border": 1})
    metadata_value = workbook.add_format({"text_wrap": True, "border": 1})
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    last_col = len(columns)
    filters = result.get("filters", {}) or {}
    scope = [f"From: {filters.get('from_date', '')}", f"To: {filters.get('to_date', '')}"]
    if filters.get("as_of_date"):
        scope.append(f"As at: {filters['as_of_date']}")
    if filters.get("budget_name"):
        scope.append(f"Budget: {filters['budget_name']}")
    for key in ("cost_centre", "branch", "business_unit", "project", "department"):
        if filters.get(key):
            scope.append(f"{key.replace('_', ' ').title()}: {filters[key]}")
    sheet.merge_range(0, 0, 0, last_col, str(result.get("name", "Financial Statement")), title)
    sheet.merge_range(1, 0, 1, last_col, "  ·  ".join(scope), subtitle)
    currency_label = result.get("base_currency") or "Company base currency"
    sheet.merge_range(2, 0, 2, last_col, f"{currency_label} values · Posted ledger records only · Generated " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), subtitle)
    sheet.write(4, 0, "Particulars", header)
    for i, col in enumerate(columns, 1):
        sheet.write_string(4, i, str(col.get("caption", col.get("code", "")))[:250], header)
        sheet.write_string(5, i, str(col.get("period_label", ""))[:250], subtitle)
    sheet.write(5, 0, "Description", header)
    row_idx = 6
    for row in rows:
        indent = max(0, min(int(row.get("indent", 0)), 8))
        text = ("    " * indent) + str(row.get("description", ""))
        is_bold, is_italic = bool(row.get("bold")), bool(row.get("italic"))
        label_format = bold_label if is_bold else (italic_label if is_italic else label)
        sheet.write_string(row_idx, 0, text[:32000], label_format)
        for i, col in enumerate(columns, 1):
            value = (row.get("values", {}) or {}).get(col.get("code"))
            if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
                sheet.write_number(row_idx, i, float(value), bold_number if is_bold else number)
            elif value is not None:
                sheet.write_string(row_idx, i, str(value)[:32000])
        row_idx += 1
    sheet.set_column(0, 0, 46)
    if columns:
        sheet.set_column(1, len(columns), 19)
    sheet.set_row(0, 30)
    sheet.set_row(4, 28)
    sheet.freeze_panes(6, 1)
    sheet.set_landscape()
    sheet.fit_to_pages(1, 0)
    sheet.repeat_rows(0, 5)
    sheet.set_margins(0.25, 0.25, 0.5, 0.5)
    sheet.set_footer("&LVeloraERP  ·  Controlled financial reporting&CPage &P of &N&RConfidential")
    if row_idx > 6 and columns:
        sheet.conditional_format(6, 1, row_idx - 1, len(columns), {"type": "cell", "criteria": "<", "value": 0,
                                                                    "format": workbook.add_format({"font_color": "#C00000"})})

    info.write(0, 0, "Report Information", title)
    info.write(2, 0, "Property", header)
    info.write(2, 1, "Value", header)
    metadata = [
        ("Report", result.get("name", "Financial Statement")),
        ("Budget", filters.get("budget_name", "")),
        ("From Date", filters.get("from_date", "")),
        ("To Date", filters.get("to_date", "")),
        ("As At Date", filters.get("as_of_date", "")),
        ("Cost Centre", filters.get("cost_centre", "All")),
        ("Branch", filters.get("branch", "All")),
        ("Business Unit", filters.get("business_unit", "All")),
        ("Project", filters.get("project", "All")),
        ("Department", filters.get("department", "All")),
        ("Data Basis", "Posted Account Ledger Records"),
        ("Currency Basis", result.get("base_currency") or "Company base currency"),
        ("Generated At (UTC)", datetime.now(timezone.utc).isoformat(timespec="seconds")),
    ]
    for idx, (key, value) in enumerate(metadata, 3):
        info.write(idx, 0, str(key), metadata_label)
        info.write(idx, 1, str(value), metadata_value)
    info.set_column(0, 0, 25)
    info.set_column(1, 1, 68)
    info.freeze_panes(3, 0)
    workbook.close()
    output.seek(0)
    return output.getvalue()



def financial_statement_pdf(result):
    """Render a board-ready, paginated PDF from an already-authorized statement result.

    ReportLab is an optional Velora capability. The PDF renderer never queries the
    ledger and therefore cannot widen the data scope established by execute_statement.
    """
    import io
    from datetime import datetime, timezone
    from xml.sax.saxutils import escape
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4, A3, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, LongTable
    except ImportError as exc:
        raise ValidationError("PDF export requires the optional 'pdf' capability. Install it with: pip install 'velora[pdf]'.") from exc

    columns = result.get("columns", [])
    rows = result.get("rows", [])
    if len(columns) > 12:
        page_size = landscape(A3)
    else:
        page_size = landscape(A4)
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=page_size, rightMargin=13*mm, leftMargin=13*mm,
                            topMargin=22*mm, bottomMargin=17*mm, title=str(result.get("name") or "Financial Statement"),
                            author="VeloraERP")
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("VeloraReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=17,
                                 leading=21, alignment=TA_LEFT, textColor=colors.HexColor("#17365D"), spaceAfter=3)
    subtitle_style = ParagraphStyle("VeloraReportSubtitle", parent=styles["Normal"], fontSize=8, leading=11,
                                    textColor=colors.HexColor("#5B6573"), spaceAfter=5)
    cell_style = ParagraphStyle("VeloraReportCell", parent=styles["Normal"], fontSize=7.2, leading=9,
                                textColor=colors.HexColor("#202A35"))
    header_style = ParagraphStyle("VeloraReportHeader", parent=cell_style, fontName="Helvetica-Bold",
                                  textColor=colors.white, alignment=TA_RIGHT)
    header_left = ParagraphStyle("VeloraReportHeaderLeft", parent=header_style, alignment=TA_LEFT)
    meta = result.get("filters", {}) or {}
    scope_parts = [f"From {meta.get('from_date', '—')}", f"To {meta.get('to_date', '—')}"]
    if meta.get("as_of_date"):
        scope_parts.append(f"As at {meta['as_of_date']}")
    if meta.get("budget_name"):
        scope_parts.append(f"Budget: {meta['budget_name']}")
    for key in ("cost_centre", "branch", "business_unit", "project", "department"):
        if meta.get(key):
            scope_parts.append(f"{key.replace('_', ' ').title()}: {meta[key]}")
    story = [Paragraph(escape(str(result.get("name") or "Financial Statement")), title_style),
             Paragraph(escape("  ·  ".join(scope_parts)), subtitle_style),
             Paragraph(escape(f"Amounts are presented in {result.get('base_currency') or 'the company base currency'}. Figures are derived from posted ledger records only."), subtitle_style),
             Spacer(1, 3*mm)]

    table_data = [[Paragraph("Particulars", header_left)] + [
        Paragraph(f"{escape(str(c.get('caption') or c.get('code') or ''))}<br/><font size='6'>{escape(str(c.get('period_label') or ''))}</font>", header_style)
        for c in columns
    ]]
    row_styles = []
    for idx, row in enumerate(rows, start=1):
        indent = max(0, min(int(row.get("indent", 0)), 10))
        label = ("&nbsp;" * (indent * 4)) + escape(str(row.get("description") or ""))
        if row.get("bold"):
            label = f"<b>{label}</b>"
        if row.get("italic"):
            label = f"<i>{label}</i>"
        cells = [Paragraph(label, cell_style)]
        values = row.get("values", {}) or {}
        for col in columns:
            value = values.get(col.get("code"))
            if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
                formatted = f"{abs(value):,.2f}"
                if value < 0:
                    formatted = f"({formatted})"
                if row.get("bold"):
                    formatted = f"<b>{formatted}</b>"
                cells.append(Paragraph(formatted, ParagraphStyle("VeloraNumeric", parent=cell_style, alignment=TA_RIGHT)))
            else:
                cells.append(Paragraph(escape(str(value)) if value is not None else "", cell_style))
        table_data.append(cells)
        if row.get("bold"):
            row_styles.append(("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#EEF3F8")))
            row_styles.append(("LINEABOVE", (0, idx), (-1, idx), 0.65, colors.HexColor("#8FA3B8")))

    usable_width = page_size[0] - 26*mm
    label_width = min(82*mm, usable_width * 0.34)
    value_width = (usable_width - label_width) / max(1, len(columns))
    table = LongTable(table_data, colWidths=[label_width] + [value_width] * len(columns), repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#D8DEE7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFBFD")]),
        *row_styles,
    ]))
    story.append(table)

    def page_decor(canvas, document):
        canvas.saveState()
        width, height = document.pagesize
        canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
        canvas.setLineWidth(0.5)
        canvas.line(13*mm, 13*mm, width-13*mm, 13*mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(13*mm, 8*mm, "VeloraERP  ·  Controlled financial reporting")
        canvas.drawRightString(width-13*mm, 8*mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=page_decor, onLaterPages=page_decor)
    output.seek(0)
    return output.getvalue()
