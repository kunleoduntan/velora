"""Bank statement readers: CSV, Excel, OFX/QFX and SWIFT MT940, normalised to one row shape.

Every reader returns a ``ParsedStatement``. Rows are ``{date, value_date, description, reference, direction, amount, balance}``
where ``direction`` is "Receipt" (money into the account, a bank credit) or "Payment" (money out, a bank debit) and ``amount`` is
always positive. Nothing here touches the database.
"""
from __future__ import annotations

import base64
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

SYNONYMS = {
    "date": ["date", "transaction date", "trans date", "txn date", "posting date", "post date", "booking date", "tran date", "trans. date", "transdate"],
    "value_date": ["value date", "value dt", "valuedate", "effective date"],
    "description": ["description", "narration", "narrative", "details", "particulars", "remarks", "transaction details", "memo", "transaction description", "payee"],
    "reference": ["reference", "ref", "ref no", "ref.", "reference no", "reference number", "cheque no", "check no", "chq no", "chq/ref no", "transaction id", "trans id", "txn id", "transaction reference", "trans ref", "session id", "fitid", "document no"],
    "debit": ["debit", "debits", "withdrawal", "withdrawals", "money out", "paid out", "payments", "payment", "dr", "debit amount", "amount debited", "withdrawal amt."],
    "credit": ["credit", "credits", "deposit", "deposits", "money in", "paid in", "receipts", "receipt", "cr", "credit amount", "amount credited", "deposit amt."],
    "amount": ["amount", "amt", "transaction amount", "value"],
    "balance": ["balance", "running balance", "closing balance", "available balance", "ledger balance", "bal"],
    "flag": ["dr/cr", "type", "cr/dr", "debit/credit", "transaction type", "dc", "indicator"],
}


class StatementError(ValueError):
    pass


@dataclass
class ParsedStatement:
    rows: list[dict] = field(default_factory=list)
    format: str = ""
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    currency: str | None = None
    account_hint: str | None = None
    warnings: list[str] = field(default_factory=list)
    skipped: int = 0


# ----------------------------------------------------------------------------------------------------------- helpers
def to_decimal(value) -> Decimal | None:
    """Parse '1,234.50', '(1,234.50)', '-1234.5', '₦1,200.00 DR', '1.234,50' (when clearly European) into a signed Decimal."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text or text in {"-", "--", "—"}:
        return None
    negative = False
    upper = text.upper()
    if re.search(r"\b(DR|D)\.?$", upper) or upper.endswith(" DR"):
        negative = True
    if re.search(r"\b(CR|C)\.?$", upper):
        negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
    cleaned = re.sub(r"[^\d,.\-+]", "", text)
    if not cleaned or cleaned in {"-", "+", ".", ","}:
        return None
    if cleaned.startswith("-"):
        negative = True
    cleaned = cleaned.lstrip("+-")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):          # 1.234,50 -> European
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        head, _, tail = cleaned.rpartition(",")
        cleaned = head.replace(",", "") + "." + tail if (len(tail) in (1, 2) and "," not in head) else cleaned.replace(",", "")
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -number if negative else number


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def to_date(value, day_first: bool = True) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if re.fullmatch(r"\d{5}", text):                         # Excel serial date
        try:
            return date.fromordinal(date(1899, 12, 30).toordinal() + int(text))
        except ValueError:
            return None
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r"^(\d{1,2})[-/. ]([A-Za-z]{3})[A-Za-z]*[-/. ,]+(\d{2,4})", text)
    if m and m[2].lower() in _MONTHS:
        y = int(m[3]); y += 2000 if y < 100 else 0
        return _mk(y, _MONTHS[m[2].lower()], int(m[1]))
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", text)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3]); y += 2000 if y < 100 else 0
        if a > 12:
            return _mk(y, b, a)
        if b > 12:
            return _mk(y, a, b)
        return _mk(y, b, a) if day_first else _mk(y, a, b)
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", text)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    return None


def _mk(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _norm_header(h) -> str:
    return re.sub(r"\s+", " ", str(h or "").strip().lower().replace("_", " "))


def detect_columns(headers: list[str]) -> dict:
    """Map our field names to column indexes by header synonym (exact match first, then 'contains')."""
    normalised = [_norm_header(h) for h in headers]
    mapping: dict[str, int] = {}
    for key, names in SYNONYMS.items():
        for name in names:
            if name in normalised and normalised.index(name) not in mapping.values():
                mapping[key] = normalised.index(name)
                break
    for key, names in SYNONYMS.items():
        if key in mapping:
            continue
        for i, h in enumerate(normalised):
            if i in mapping.values() or not h:
                continue
            if any(len(n) > 3 and n in h for n in names):
                mapping[key] = i
                break
    return mapping


def _dedupe(rows: list[dict]) -> list[dict]:
    return rows


# ------------------------------------------------------------------------------------------------------------- tabular
def parse_table(table: list[list], *, day_first: bool = True, amount_sign: str = "credit_positive", column_map: dict | None = None,
                fmt: str = "CSV") -> ParsedStatement:
    """Parse an already-split table (CSV or worksheet). Finds the header row itself, so bank preambles are skipped."""
    out = ParsedStatement(format=fmt)
    header_idx, mapping = None, None
    for i, row in enumerate(table[:60]):
        m = detect_columns([str(c or "") for c in row])
        if "date" in m and ("amount" in m or "debit" in m or "credit" in m):
            header_idx, mapping = i, m
            break
    if header_idx is None:
        raise StatementError("Could not find a header row with a date and an amount (or debit/credit) column. Check the file or map the columns.")
    if column_map:
        headers = [_norm_header(h) for h in table[header_idx]]
        for key, name in column_map.items():
            if name and _norm_header(name) in headers:
                mapping[key] = headers.index(_norm_header(name))
    for row in table[header_idx + 1:]:
        if not row or not any(str(c or "").strip() for c in row):
            continue

        def cell(key):
            idx = mapping.get(key)
            return row[idx] if idx is not None and idx < len(row) else None

        d = to_date(cell("date"), day_first)
        if d is None:
            # totals / footer / page break rows
            if any(str(c or "").strip() for c in row):
                out.skipped += 1
            continue
        debit, credit, amount = to_decimal(cell("debit")), to_decimal(cell("credit")), to_decimal(cell("amount"))
        signed: Decimal | None = None
        if debit or credit:
            signed = abs(credit or Decimal(0)) - abs(debit or Decimal(0))
        elif amount is not None:
            flag = str(cell("flag") or "").strip().upper()
            if flag in {"DR", "D", "DEBIT", "DB", "WITHDRAWAL"}:
                signed = -abs(amount)
            elif flag in {"CR", "C", "CREDIT", "DEPOSIT"}:
                signed = abs(amount)
            else:
                signed = amount if amount_sign == "credit_positive" else -amount
        if not signed:
            out.skipped += 1
            continue
        out.rows.append({
            "date": d, "value_date": to_date(cell("value_date"), day_first),
            "description": re.sub(r"\s+", " ", str(cell("description") or "")).strip(),
            "reference": re.sub(r"\s+", " ", str(cell("reference") or "")).strip(),
            "direction": "Receipt" if signed > 0 else "Payment", "amount": abs(signed), "balance": to_decimal(cell("balance")),
        })
    if not out.rows:
        raise StatementError("The file has a header but no readable transaction rows.")
    _balances_from_running(out)
    return out


def _balances_from_running(out: ParsedStatement) -> None:
    """If a running-balance column exists, derive opening/closing balances and warn when the arithmetic does not hold."""
    withbal = [r for r in out.rows if r.get("balance") is not None]
    if not withbal:
        return
    ordered = out.rows
    first, last = ordered[0], ordered[-1]
    asc = (first["date"], 0) <= (last["date"], 0)
    top, bottom = (first, last) if asc else (last, first)
    sign = lambda r: r["amount"] if r["direction"] == "Receipt" else -r["amount"]
    if top.get("balance") is not None:
        out.opening_balance = top["balance"] - sign(top)
    if bottom.get("balance") is not None:
        out.closing_balance = bottom["balance"]
    if out.opening_balance is not None and out.closing_balance is not None:
        net = sum((sign(r) for r in out.rows), Decimal(0))
        if abs(out.opening_balance + net - out.closing_balance) > Decimal("0.01"):
            out.warnings.append("The running balances in the file do not add up to the listed transactions; some rows may be missing or out of order.")


def parse_csv(text: str, **kw) -> ParsedStatement:
    text = text.lstrip("﻿")
    sample = "\n".join(text.splitlines()[:40])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    table = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    return parse_table(table, fmt="CSV", **kw)


def parse_xlsx(data: bytes, **kw) -> ParsedStatement:
    try:
        import openpyxl
    except ImportError as exc:
        raise StatementError("Excel statements need the openpyxl package. Save the statement as CSV, or install openpyxl.") from exc
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    table = [list(r) for r in wb.active.iter_rows(values_only=True)]
    return parse_table(table, fmt="Excel", **kw)


# ----------------------------------------------------------------------------------------------------------- OFX / QFX
def parse_ofx(text: str, **kw) -> ParsedStatement:
    out = ParsedStatement(format="OFX")

    def tag(block, name):
        m = re.search(rf"<{name}>\s*([^<\r\n]*)", block, re.I)
        return m.group(1).strip() if m else None

    out.currency = tag(text, "CURDEF")
    out.account_hint = tag(text, "ACCTID")
    for m in re.finditer(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", text, re.I | re.S):
        block = m.group(1)
        amt = to_decimal(tag(block, "TRNAMT"))
        d = to_date((tag(block, "DTPOSTED") or "")[:8])
        if amt is None or d is None or amt == 0:
            out.skipped += 1
            continue
        name, memo = tag(block, "NAME") or "", tag(block, "MEMO") or ""
        out.rows.append({"date": d, "value_date": to_date((tag(block, "DTUSER") or "")[:8]), "description": " ".join(x for x in (name, memo) if x),
                         "reference": tag(block, "CHECKNUM") or tag(block, "FITID") or "", "direction": "Receipt" if amt > 0 else "Payment",
                         "amount": abs(amt), "balance": None})
    led = re.search(r"<LEDGERBAL>.*?<BALAMT>\s*([^<\r\n]+)", text, re.I | re.S)
    if led:
        out.closing_balance = to_decimal(led.group(1))
    if not out.rows:
        raise StatementError("No transactions were found in the OFX file.")
    if out.closing_balance is not None:
        net = sum((r["amount"] if r["direction"] == "Receipt" else -r["amount"] for r in out.rows), Decimal(0))
        out.opening_balance = out.closing_balance - net
    return out


# ---------------------------------------------------------------------------------------------------------------- MT940
def _mt_amount(text: str) -> Decimal:
    return Decimal(text.replace(",", "."))


def _mt_date(yymmdd: str) -> date | None:
    try:
        y = int(yymmdd[:2])
        return date(2000 + y if y < 80 else 1900 + y, int(yymmdd[2:4]), int(yymmdd[4:6]))
    except ValueError:
        return None


def parse_mt940(text: str, **kw) -> ParsedStatement:
    out = ParsedStatement(format="MT940")
    text = text.replace("\r", "")
    m = re.search(r":25:([^\n]+)", text)
    out.account_hint = m.group(1).strip() if m else None
    opening = re.search(r":60[FM]:([CD])(\d{6})([A-Z]{3})([\d,]+)", text)
    if opening:
        out.opening_balance = _mt_amount(opening.group(4)) * (1 if opening.group(1) == "C" else -1)
        out.currency = opening.group(3)
    closing = None
    for closing in re.finditer(r":62[FM]:([CD])(\d{6})([A-Z]{3})([\d,]+)", text):
        pass
    if closing:
        out.closing_balance = _mt_amount(closing.group(4)) * (1 if closing.group(1) == "C" else -1)
    # transactions: :61: line then optional :86: narrative
    for m in re.finditer(r":61:(\d{6})(\d{4})?(R?[CD])[A-Z]?([\d,]+)N([A-Z0-9]{3})([^\n]*)((?:\n(?!:)[^\n]*)*)\n?(?::86:((?:[^\n]*)(?:\n(?!:)[^\n]*)*))?", text):
        vdate = _mt_date(m.group(1))
        indicator = m.group(3)
        amount = _mt_amount(m.group(4))
        ref = (m.group(6) or "").split("//")[0].strip()
        info = re.sub(r"\s+", " ", (m.group(8) or "").replace("\n", " ")).strip()
        info = re.sub(r"\?\d{2}", " ", info).strip()
        receipt = indicator in ("C", "RD")           # RD (reversal of a debit) is money back in
        if vdate is None or amount == 0:
            out.skipped += 1
            continue
        out.rows.append({"date": vdate, "value_date": vdate, "description": info or ref, "reference": ref if ref.upper() != "NONREF" else "",
                         "direction": "Receipt" if receipt else "Payment", "amount": amount, "balance": None})
    if not out.rows:
        raise StatementError("No :61: transaction lines were found in the MT940 file.")
    if out.opening_balance is not None and out.closing_balance is not None:
        net = sum((r["amount"] if r["direction"] == "Receipt" else -r["amount"] for r in out.rows), Decimal(0))
        if abs(out.opening_balance + net - out.closing_balance) > Decimal("0.01"):
            out.warnings.append("The MT940 opening balance plus its transactions does not equal its closing balance.")
    return out


# ------------------------------------------------------------------------------------------------------------- dispatch
def detect_format(content: str, filename: str = "") -> str:
    name = (filename or "").lower()
    head = content[:4000]
    if name.endswith((".ofx", ".qfx")) or "<OFX>" in head.upper() or "OFXHEADER" in head.upper():
        return "OFX"
    if name.endswith((".sta", ".mt940", ".940", ".swi")) or re.search(r"^:20:|^:61:", head, re.M):
        return "MT940"
    return "CSV"


def parse_statement(*, content: str | None = None, content_base64: str | None = None, filename: str = "", fmt: str | None = None,
                    day_first: bool = True, amount_sign: str = "credit_positive", column_map: dict | None = None) -> ParsedStatement:
    """Entry point. ``content`` is text; ``content_base64`` carries binary files such as .xlsx."""
    name = (filename or "").lower()
    if content_base64:
        data = base64.b64decode(content_base64)
        if fmt in (None, "", "Excel") and (name.endswith((".xlsx", ".xlsm")) or data[:2] == b"PK"):
            return parse_xlsx(data, day_first=day_first, amount_sign=amount_sign, column_map=column_map)
        content = data.decode("utf-8-sig", errors="replace")
    if not content or not content.strip():
        raise StatementError("The statement is empty.")
    fmt = (fmt or "").upper() or detect_format(content, filename)
    if fmt == "OFX":
        return parse_ofx(content)
    if fmt == "MT940":
        return parse_mt940(content)
    return parse_csv(content, day_first=day_first, amount_sign=amount_sign, column_map=column_map)
