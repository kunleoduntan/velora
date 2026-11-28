"""Excel / CSV in and out for the batch documents.

* a generated TEMPLATE with an Instructions sheet
* IMPORT matches columns by HEADER NAME (order does not matter; a bank's own headers such as Withdrawal/Deposit are understood),
  reports every bad row individually and still imports the good ones
* EXPORT writes the same layout the import reads
* anything that looks like a formula is stored as plain text (no formula injection), and files are size/row limited
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from velora import ValidationError

from . import common as c

MAX_BYTES, MAX_ROWS = 5_000_000, 5000
COLUMNS = [("Date", "posting_date"), ("Type", "trans_type"), ("Bank Account", "bank_account"), ("Money In", "inflow"), ("Money Out", "outflow"),
           ("Account", "account"), ("Party Type", "party_type"), ("Party", "party"), ("Narration", "narration"), ("Reference", "reference_no"),
           ("Method", "method"), ("WHT %", "wht_rate"), ("Fee", "fee_amount"), ("Amortise", "amortise"), ("Spread Over (months)", "spread_periods"),
           ("Expense Account", "expense_account"), ("Amortise From", "amortise_from"), ("Allow Duplicate", "allow_duplicate")]
HEADER_MAP = {}
for label, field in COLUMNS:
    HEADER_MAP[re.sub(r"[^a-z0-9%]+", " ", label.lower()).strip()] = field
# headings a bank or accountant commonly uses
for field, phrases in {
    "inflow": ["money in", "deposit", "deposits", "credit", "credits", "paid in", "received", "lodgement"],
    "outflow": ["money out", "withdrawal", "withdrawals", "debit", "debits", "paid out", "payment"],
    "posting_date": ["date", "transaction date", "value date", "posting date", "trans date"],
    "narration": ["description", "remark", "remarks", "details", "particulars", "memo", "narrative", "narration"],
    "reference_no": ["reference", "ref", "reference no", "reference number", "transaction reference", "cheque no"],
    "bank_account": ["bank", "bank account", "cash account"], "trans_type": ["type", "transaction type"],
    "account": ["account", "gl account", "counter account", "category"], "wht_rate": ["wht", "wht %", "wht rate"],
    "spread_periods": ["spread over months", "spread over", "spread periods", "months", "spread over months"], "amortise_from": ["amortise from", "start"],
    "allow_duplicate": ["allow duplicate", "duplicate ok"], "party_type": ["party type"], "party": ["party", "customer", "supplier", "payee"],
    "method": ["method", "payment method"], "fee_amount": ["fee", "fees", "charge"], "expense_account": ["expense account", "expense"], "amortise": ["amortise", "amortize", "prepaid"],
}.items():
    for p in phrases:
        HEADER_MAP[p] = field
LABELS = {field: label for label, field in COLUMNS}
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
TYPES = {"Receipt", "Payment", "Transfer"}
PARTY_TYPES = {"Customer", "Supplier", "Employee"}
METHODS = {"Cash", "Bank Transfer", "Cheque", "Card", "Gateway"}
INSTRUCTIONS = [
    "HOW TO USE THIS SHEET", "",
    "Fill the 'Transactions' sheet, one row per bank/cash movement. Column ORDER does not matter; columns are found by their heading.",
    "Money In = money that came into the bank (deposits/credits). Money Out = money that left (withdrawals/debits). Use one or the other, never both, never a negative number.",
    "Type: leave blank - Receipt for Money In, Payment for Money Out. Use Transfer to move money between your own bank/cash accounts (Account = the other one).",
    "Account: the income/expense/other account the money is for. Leave it blank and name a Customer (money in) or Supplier/Employee (money out) to settle that party's account.",
    "Date: YYYY-MM-DD, or DD/MM/YYYY (day first). Amounts: plain numbers; thousands commas are fine; at most 2 decimals.",
    "Reference: the bank's reference. A row whose bank, date, amount and reference already exist is refused (so importing a statement twice is safe) unless 'Allow Duplicate' is Yes.",
    "WHT % applies to the amount as the gross. Fee (receipts only) is the gateway/bank fee deducted from the money received.",
    "Amortise = Yes on a Payment row spreads the cost over 'Spread Over (months)' months into 'Expense Account'.",
    "Rows with problems are reported individually; the good rows are still imported.",
]


def _norm(h) -> str:
    return re.sub(r"[^a-z0-9%]+", " ", str(h or "").lower()).strip()


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _date(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _text(v)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"{s!r} is not a date (use YYYY-MM-DD or DD/MM/YYYY)")


def _num(v, what):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float, Decimal)):
        d = Decimal(str(v))
    else:
        s = _text(v).replace(",", "").replace("₦", "").replace("NGN", "").strip()
        try:
            d = Decimal(s)
        except InvalidOperation:
            raise ValueError(f"{what} {v!r} is not a number") from None
    if d < 0:
        raise ValueError(f"{what} cannot be negative")
    return d


def _flag(v) -> int:
    return 1 if _text(v).lower() in ("1", "y", "yes", "true", "x") else 0


def _style(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    for cell in ws[1]:
        cell.font, cell.fill, cell.alignment = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="305496"), Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = "A2"


def _put(ws, r, col, v):
    cell = ws.cell(r, col)
    if isinstance(v, str) and v.startswith(FORMULA_START):
        cell.value, cell.data_type = v, "s"                    # text, never a formula
    else:
        cell.value = v
    return cell


def template_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append([h for h, _ in COLUMNS])
    ws.append([date.today().isoformat(), "", "", "", 50000, "Rent", "", "", "Office rent January", "REF-001"] + [""] * 8)
    _style(ws, [12, 10, 20, 14, 14, 24, 12, 18, 30, 16, 14, 8, 10, 10, 12, 20, 14, 12])
    for cell in ws[2]:
        cell.font = Font(italic=True, color="808080")
    ins = wb.create_sheet("Instructions")
    for i, line in enumerate(INSTRUCTIONS, 1):
        ins.cell(i, 1).value = line
    ins["A1"].font = Font(bold=True, size=13)
    ins.column_dimensions["A"].width = 130
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_bytes(doc) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append([h for h, _ in COLUMNS] + ["Status", "Created Document"])
    for r, row in enumerate(doc.lines, 2):
        for i, (_, field) in enumerate(COLUMNS, 1):
            v = row.get(field)
            if field in ("amortise", "allow_duplicate"):
                v = "Yes" if v else ""
            elif isinstance(v, Decimal):
                v = float(v) if v else None
            _put(ws, r, i, v if v not in ("", 0) or field == "inflow" else None)
        _put(ws, r, len(COLUMNS) + 1, row.status)
        _put(ws, r, len(COLUMNS) + 2, row.created_ref)
    _style(ws, [12, 10, 20, 14, 14, 24, 12, 18, 30, 16, 14, 8, 10, 10, 12, 20, 14, 12, 12, 18])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _read(content: bytes, filename: str) -> list[list]:
    if len(content) > MAX_BYTES:
        raise ValidationError(f"The file is larger than {MAX_BYTES // 1_000_000} MB")
    if filename.lower().endswith(".csv") or not content[:2] == b"PK":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        return [list(r) for r in csv.reader(io.StringIO(text))]
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb["Transactions"] if "Transactions" in wb.sheetnames else wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    except Exception as e:  # noqa: BLE001 - any corrupt/odd file becomes one clear message
        raise ValidationError(f"Could not read the file as Excel or CSV ({type(e).__name__})") from None


def import_rows(doc, content: bytes, filename: str = "", replace: bool = False) -> dict:
    """Append the file's rows to a DRAFT batch. Returns {'imported': n, 'errors': [{'row': excel_row, 'error': msg}], 'unknown_columns': [...]}.
    Nothing is saved: call doc.save() (which pre-flights every row) when you are happy."""
    if doc.docstatus != 0:
        raise ValidationError("Rows can only be imported into a draft batch")
    grid = _read(content, filename)
    if not grid:
        raise ValidationError("The file is empty")
    head_idx = next((i for i, r in enumerate(grid) if any(_norm(x) in HEADER_MAP for x in r)), None)
    if head_idx is None:
        raise ValidationError("No recognisable column headings found. Download the template to see the expected headings.")
    cols, unknown = {}, []
    for i, h in enumerate(grid[head_idx]):
        f = HEADER_MAP.get(_norm(h))
        if f and f not in cols.values():
            cols[i] = f
        elif _text(h) and _norm(h) not in ("status", "created document"):
            unknown.append(_text(h))
    if not ({"inflow", "outflow"} & set(cols.values())):
        raise ValidationError("The file needs a 'Money In' and/or 'Money Out' column (a bank's Deposit/Withdrawal or Credit/Debit also work)")
    body = grid[head_idx + 1:]
    if len(body) > MAX_ROWS:
        raise ValidationError(f"At most {MAX_ROWS} rows per import")
    if replace:
        doc.set("lines", [r for r in doc.lines if r.created_ref])
    accounts_needed = {_text(r[i]) for r in body for i, f in cols.items() if f in ("bank_account", "account", "expense_account") and i < len(r) and _text(r[i])}
    known = c.accounts_info(accounts_needed)
    errors, imported = [], 0
    for n, raw in enumerate(body, head_idx + 2):
        if not any(_text(x) for x in raw):
            continue
        try:
            vals = {}
            for i, f in cols.items():
                v = raw[i] if i < len(raw) else None
                if f == "posting_date" or f == "amortise_from":
                    vals[f] = _date(v)
                elif f in ("inflow", "outflow", "fee_amount"):
                    vals[f] = _num(v, LABELS[f])
                elif f == "wht_rate":
                    vals[f] = float(_num(v, "WHT %") or 0)
                elif f == "spread_periods":
                    vals[f] = int(_num(v, "Spread Over") or 0)
                elif f in ("amortise", "allow_duplicate"):
                    vals[f] = _flag(v)
                else:
                    vals[f] = _text(v) or None
            for f in ("bank_account", "account", "expense_account"):
                if vals.get(f) and vals[f] not in known:
                    raise ValueError(f"account {vals[f]!r} does not exist")
            if vals.get("trans_type") and vals["trans_type"].title() not in TYPES:
                raise ValueError(f"Type {vals['trans_type']!r} must be Receipt, Payment or Transfer (or blank)")
            if vals.get("trans_type"):
                vals["trans_type"] = vals["trans_type"].title()
            if vals.get("party_type") and vals["party_type"].title() not in PARTY_TYPES:
                raise ValueError(f"Party Type {vals['party_type']!r} must be Customer, Supplier or Employee")
            if vals.get("party_type"):
                vals["party_type"] = vals["party_type"].title()
            if vals.get("method") and vals["method"].title() not in {m.title() for m in METHODS}:
                raise ValueError(f"Method {vals['method']!r} is not one of {', '.join(sorted(METHODS))}")
            if vals.get("method"):
                vals["method"] = next(m for m in METHODS if m.lower() == vals["method"].lower())
            if not vals.get("inflow") and not vals.get("outflow"):
                raise ValueError("enter an amount in Money In or Money Out")
            if vals.get("inflow") and vals.get("outflow"):
                raise ValueError("enter Money In or Money Out, not both")
            for f in ("inflow", "outflow", "fee_amount"):
                if vals.get(f) is not None:
                    vals[f] = c.money(vals[f], f)
            doc.append("lines", {k: v for k, v in vals.items() if v is not None})
            imported += 1
        except (ValueError, ValidationError) as e:
            errors.append({"row": n, "error": str(e)})
    return {"imported": imported, "errors": errors, "unknown_columns": unknown}
