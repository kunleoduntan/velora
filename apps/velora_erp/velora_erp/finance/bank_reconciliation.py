"""Bank reconciliation service: statement import, automatic matching, review, posting of unrecorded items and the reconciliation statement.

Data model
  Bank Statement Line            one line of a bank statement; lines persist until matched, so nothing is lost between statements.
  Bank Reconciliation Match      links statement lines and ledger entries (Account Ledger Record) into balanced groups.
  Bank Reconciliation            the period-end statement that proves the ledger agrees with the bank.

Sign convention: positive = money in (receipt), negative = money out (payment), on both sides.
Nothing here posts to the ledger directly. Bank items that are not yet in the books are proposed through the existing
Bank Transaction Coding Rules and raised as a Batch Bank Transaction, which follows the configured approval authority.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from velora import get_doc, get_list, new_doc, throw

from . import bank_matching as engine
from . import bank_statement_parsers as parsers
from .multicurrency import base_currency

CENT = Decimal("0.01")
LEDGER_FIELDS = ["name", "posting_date", "transaction_date", "debit", "credit", "base_debit", "base_credit", "currency", "external_reference",
                 "settlement_reference", "source_doctype", "source_name", "line_description", "party", "source_line_reference"]


def D(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(CENT)


def _d(v) -> date | None:
    if not v:
        return None
    return v if isinstance(v, date) and not isinstance(v, datetime) else (v.date() if isinstance(v, datetime) else date.fromisoformat(str(v)[:10]))


# ------------------------------------------------------------------------------------------------------------------- access
def bank(name: str):
    if not name:
        throw("Choose a bank account.")
    try:
        doc = get_doc("Bank Account", name, ignore_permissions=True)
    except Exception:
        throw(f"Bank Account {name!r} was not found.")
    if doc.disabled:
        throw("This bank account is disabled.")
    return doc


def settings(b) -> dict:
    return {"threshold": float(b.auto_accept_threshold or 90), "date_tol": int(b.date_tolerance_days if b.date_tolerance_days is not None else 4),
            "amount_tol": D(b.amount_tolerance), "day_first": "Month" not in (b.statement_date_order or "")}


def _cur(b) -> str:
    return (b.currency or base_currency()).upper()


def _signed(rec: dict, cur: str) -> Decimal:
    if (rec.get("currency") or cur).upper() == cur:
        return D(rec.get("debit")) - D(rec.get("credit"))
    return D(rec.get("base_debit")) - D(rec.get("base_credit"))


def ledger_records(b, to_date=None) -> list[dict]:
    filters = [["account", "=", b.gl_account]]
    if to_date:
        filters.append(["posting_date", "<=", str(to_date)])
    rows = get_list("Account Ledger Record", filters=filters, fields=LEDGER_FIELDS, order_by="posting_date asc", limit=200000, ignore_permissions=True)
    cur = _cur(b)
    out = []
    for r in rows:
        s = _signed(r, cur)
        if s == 0:
            continue
        refs = [x for x in (r.get("external_reference"), r.get("settlement_reference"), r.get("source_name"), r.get("source_line_reference")) if x]
        out.append({"id": r["name"], "date": _d(r["posting_date"]), "signed": s, "refs": refs, "text": r.get("line_description") or "",
                    "party": r.get("party"), "source_doctype": r.get("source_doctype"),
                    "source_name": r.get("source_name"), "reference": r.get("external_reference") or r.get("source_name") or ""})
    return out


def lines_of(b, to_date=None, statuses=None) -> list[dict]:
    filters = [["bank_account", "=", b.name]]
    if to_date:
        filters.append(["posting_date", "<=", str(to_date)])
    if statuses:
        filters.append(["status", "in", list(statuses)])
    return get_list("Bank Statement Line", filters=filters, fields=["name", "posting_date", "direction", "amount", "description", "reference", "counterparty", "status",
                                                                      "match_group", "reconciliation", "proposed_account", "posting_batch", "running_balance", "ignore_reason", "coding_rule"],
                    order_by="posting_date asc", limit=200000, ignore_permissions=True)


def _line_item(l: dict) -> dict:
    sign = 1 if l["direction"] == "Receipt" else -1
    return {"id": l["name"], "date": _d(l["posting_date"]), "signed": sign * D(l["amount"]), "reference": l.get("reference") or "",
            "description": l.get("description") or "", "counterparty": l.get("counterparty") or "", "aliases": [l["name"]]}


def matches_of(bank_account: str, statuses=("Suggested", "Confirmed")) -> list[dict]:
    return get_list("Bank Reconciliation Match", filters=[["bank_account", "=", bank_account], ["status", "in", list(statuses)]],
                    fields=["name", "match_group", "statement_line", "ledger_record", "signed_amount", "status", "method", "confidence", "reason", "reconciliation"],
                    limit=400000, ignore_permissions=True)


# ------------------------------------------------------------------------------------------------------------------ import
def import_statement(bank_account: str, *, content=None, content_base64=None, filename="", fmt=None, amount_sign="credit_positive", column_map=None,
                     auto=True, source_label=None) -> dict:
    b = bank(bank_account)
    st = settings(b)
    try:
        parsed = parsers.parse_statement(content=content, content_base64=content_base64, filename=filename, fmt=fmt, day_first=st["day_first"],
                                         amount_sign=amount_sign, column_map=column_map)
    except parsers.StatementError as exc:
        throw(str(exc))
    cur = _cur(b)
    if parsed.currency and parsed.currency.upper() != cur:
        throw(f"The statement is in {parsed.currency.upper()} but this bank account is in {cur}.")
    batch_id = f"IMP-{datetime.now(timezone.utc).replace(tzinfo=None):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4]}"
    seen: dict[tuple, int] = {}
    created = duplicates = 0
    existing = {r["line_hash"] for r in get_list("Bank Statement Line", filters=[["bank_account", "=", b.name]], fields=["line_hash"], limit=500000, ignore_permissions=True)}
    for row in parsed.rows:
        key = (b.name, str(row["date"]), row["direction"], str(D(row["amount"])), (row["reference"] or "").strip().upper(), (row["description"] or "").strip().upper())
        seen[key] = seen.get(key, 0) + 1
        h = hashlib.sha1(("|".join(key) + f"|{seen[key]}").encode()).hexdigest()
        if h in existing:
            duplicates += 1
            continue
        existing.add(h)
        new_doc("Bank Statement Line", bank_account=b.name, posting_date=row["date"], value_date=row.get("value_date"), direction=row["direction"],
                amount=D(row["amount"]), currency=cur, description=row["description"], reference=row["reference"], running_balance=row.get("balance"),
                status="Unmatched", import_batch=batch_id, line_hash=h).insert(ignore_permissions=True)
        created += 1
    result = {"import_batch": batch_id, "format": parsed.format, "rows_read": len(parsed.rows), "created": created, "duplicates_skipped": duplicates,
              "unreadable_rows": parsed.skipped, "opening_balance": str(parsed.opening_balance) if parsed.opening_balance is not None else None,
              "closing_balance": str(parsed.closing_balance) if parsed.closing_balance is not None else None, "warnings": parsed.warnings,
              "first_date": str(min(r["date"] for r in parsed.rows)), "last_date": str(max(r["date"] for r in parsed.rows))}
    if auto and created:
        result["matching"] = run_auto(b.name)
    return result


# -------------------------------------------------------------------------------------------------------------- matching
def _new_group() -> str:
    return "MG-" + uuid.uuid4().hex[:10].upper()


def _save_group(b, g: engine.Group, status: str, lines: dict, recs: dict) -> None:
    gid = _new_group()
    for sid in g.lines:
        new_doc("Bank Reconciliation Match", bank_account=b.name, match_group=gid, statement_line=sid, signed_amount=lines[sid]["signed"], status=status,
                method=g.method, confidence=g.confidence, reason=g.reason).insert(ignore_permissions=True)
        _set_line(sid, status="Matched" if status == "Confirmed" else "Suggested", match_group=gid)
    for rid in g.records:
        new_doc("Bank Reconciliation Match", bank_account=b.name, match_group=gid, ledger_record=rid, signed_amount=recs[rid]["signed"], status=status,
                method=g.method, confidence=g.confidence, reason=g.reason).insert(ignore_permissions=True)


def _set_line(name: str, **values) -> None:
    doc = get_doc("Bank Statement Line", name, ignore_permissions=True)
    for k, v in values.items():
        setattr(doc, k, v)
    doc.save(ignore_permissions=True)


def run_auto(bank_account: str, *, to_date=None, post=None) -> dict:
    """Match everything that is still open; confirm what is certain, suggest the rest, code what has no counterpart."""
    b = bank(bank_account)
    st = settings(b)
    all_matches = matches_of(b.name, ("Suggested", "Confirmed", "Rejected"))
    taken_rec = {m["ledger_record"] for m in all_matches if m["ledger_record"] and m["status"] != "Rejected"}
    rejected: set = set()
    by_group: dict = {}
    for m in all_matches:
        by_group.setdefault(m["match_group"], []).append(m)
    for ms in by_group.values():
        if ms[0]["status"] == "Rejected":
            for a in ms:
                for c in ms:
                    if a["statement_line"] and c["ledger_record"]:
                        rejected.add((a["statement_line"], c["ledger_record"]))
    doubted = {a for a, _ in rejected}
    lines = {l["name"]: _line_item(l) for l in lines_of(b, to_date, ("Unmatched",))}
    recs = {r["id"]: r for r in ledger_records(b, to_date) if r["id"] not in taken_rec}
    counts = {"confirmed": 0, "suggested": 0}

    # pre-pass: lines this system itself posted through a bank batch match their own ledger entries with certainty
    line_docs = {l["name"]: l for l in lines_of(b, to_date, ("Unmatched",))}
    for lid, l in list(line_docs.items()):
        batch = l.get("posting_batch")
        if not batch:
            continue
        want = lines[lid]["signed"]
        ref = l.get("reference") or lid
        for rid, r in list(recs.items()):
            if r.get("source_name") == batch and r["signed"] == want and (r.get("reference") or "") == ref:
                g = engine.Group([lid], [rid], "Posted from Statement", 100.0, f"Posted from this statement line through {batch}")
                _save_group(b, g, "Confirmed", lines, recs)
                counts["confirmed"] += 1
                lines.pop(lid); recs.pop(rid)
                break

    groups = engine.match(list(lines.values()), list(recs.values()), date_tolerance=st["date_tol"], amount_tolerance=st["amount_tol"], auto_accept=st["threshold"], excluded=rejected)
    for g in groups:
        confirm = g.confidence >= st["threshold"]
        if confirm and any(l in doubted for l in g.lines):
            confirm = False  # a person already turned down a pairing for this line: the next candidate is shown, never silently confirmed
        _save_group(b, g, "Confirmed" if confirm else "Suggested", lines, recs)
        counts["confirmed" if confirm else "suggested"] += 1
    coded = code_unmatched(b.name)
    out = {**counts, **coded}
    if (post if post is not None else b.auto_post_coded) and coded["coded"]:
        out["batch"] = post_coded_lines(b.name)
    return out


def code_unmatched(bank_account: str) -> dict:
    """Propose an offset account for open statement lines using the Bank Transaction Coding Rules (the same rules the statement importer uses)."""
    b = bank(bank_account)
    rules = get_list("Bank Transaction Coding Rule", filters={"disabled": 0}, fields=["name", "priority", "match_field", "match_operator", "match_text",
                                                                                      "direction", "offset_account", "party_type", "party", "cost_centre", "valid_from", "valid_to"],
                     limit=10000, ignore_permissions=True)
    rules.sort(key=lambda r: (int(r.get("priority") or 100), r["name"]))
    coded = uncoded = 0
    for l in lines_of(b, None, ("Unmatched",)):
        if l.get("proposed_account") or l.get("posting_batch"):
            continue
        hit = None
        for r in rules:
            if r.get("direction") and r["direction"] != l["direction"]:
                continue
            if r.get("valid_from") and str(l["posting_date"]) < str(r["valid_from"]):
                continue
            if r.get("valid_to") and str(l["posting_date"]) > str(r["valid_to"]):
                continue
            src = ((l.get("description") if r["match_field"] == "Description" else l.get("reference")) or "").casefold()
            tgt = r["match_text"].casefold()
            ok = tgt in src if r["match_operator"] == "Contains" else src.startswith(tgt) if r["match_operator"] == "Starts With" else src == tgt
            if ok:
                hit = r
                break
        if hit:
            _set_line(l["name"], proposed_account=hit["offset_account"], proposed_party_type=hit.get("party_type"), proposed_party=hit.get("party"),
                      proposed_cost_centre=hit.get("cost_centre"), coding_rule=hit["name"])
            coded += 1
        else:
            uncoded += 1
    return {"coded": coded, "uncoded": uncoded}


def post_coded_lines(bank_account: str) -> dict:
    """Raise one Batch Bank Transaction for the coded lines that have no ledger entry. It still follows the approval authority."""
    b = bank(bank_account)
    todo = [l for l in lines_of(b, None, ("Unmatched",)) if l.get("proposed_account") and not l.get("posting_batch")]
    if not todo:
        return {"batch": None, "lines": 0}
    docs = {l["name"]: l for l in todo}
    rows = []
    for l in todo:
        full = get_doc("Bank Statement Line", l["name"], ignore_permissions=True)
        rows.append({"transaction_date": full.posting_date, "direction": full.direction, "description": (full.description or full.reference or "Bank statement line")[:140],
                     "offset_account": full.proposed_account, "party_type": full.proposed_party_type or None, "party": full.proposed_party or None, "amount": full.amount,
                     "reference": full.reference or full.name, "cost_centre": full.proposed_cost_centre or None})
    batch = new_doc("Batch Bank Transaction", bank_account=b.gl_account, posting_date=max(str(r["transaction_date"]) for r in rows),
                    currency=_cur(b), exchange_rate=1, reference=f"Statement lines {b.name}", approval_status="Pending", transactions=rows)
    batch.insert(ignore_permissions=True)
    for name in docs:
        _set_line(name, posting_batch=batch.name)
    return {"batch": batch.name, "lines": len(rows)}


# ----------------------------------------------------------------------------------------------------- review actions
def _locked(group_rows) -> bool:
    return any(m.get("reconciliation") for m in group_rows)


def _group_rows(group: str) -> list[dict]:
    rows = get_list("Bank Reconciliation Match", filters=[["match_group", "=", group]], fields=["name", "match_group", "statement_line", "ledger_record", "signed_amount", "status", "reconciliation", "bank_account"],
                    limit=1000, ignore_permissions=True)
    if not rows:
        throw(f"Match group {group} was not found.")
    return rows


def confirm_groups(groups: list[str]) -> int:
    n = 0
    for g in groups:
        rows = _group_rows(g)
        for m in rows:
            doc = get_doc("Bank Reconciliation Match", m["name"], ignore_permissions=True)
            doc.status = "Confirmed"
            doc.save(ignore_permissions=True)
            if m["statement_line"]:
                _set_line(m["statement_line"], status="Matched")
        n += 1
    return n


def _release(rows, *, reject=False) -> None:
    for m in rows:
        if m["statement_line"]:
            _set_line(m["statement_line"], status="Unmatched", match_group=None)
        doc = get_doc("Bank Reconciliation Match", m["name"], ignore_permissions=True)
        if reject:
            doc.status = "Rejected"
            doc.save(ignore_permissions=True)
        else:
            doc.delete(ignore_permissions=True)


def reject_groups(groups: list[str]) -> int:
    """Reject a suggestion: its pairing is remembered so the engine never proposes the same pairing again."""
    for g in groups:
        rows = _group_rows(g)
        if _locked(rows):
            throw("This match belongs to a submitted reconciliation. Cancel that reconciliation first.")
        _release(rows, reject=True)
    return len(groups)


def unmatch(group: str) -> int:
    rows = _group_rows(group)
    if _locked(rows):
        throw("This match belongs to a submitted reconciliation. Cancel that reconciliation first.")
    _release(rows)
    return len(rows)


def manual_match(bank_account: str, line_ids: list[str], record_ids: list[str], reason: str | None = None) -> dict:
    b = bank(bank_account)
    if not line_ids and not record_ids:
        throw("Select at least one bank line or ledger entry.")
    lines = {l["name"]: l for l in lines_of(b)}
    recs = {r["id"]: r for r in ledger_records(b)}
    for lid in line_ids:
        if lid not in lines:
            throw(f"Bank line {lid} does not belong to this account.")
        if lines[lid]["status"] == "Ignored" or lines[lid].get("reconciliation"):
            throw(f"Bank line {lid} is ignored or locked and cannot be matched.")
    taken = {m["ledger_record"]: m for m in matches_of(b.name) if m["ledger_record"]}
    for rid in record_ids:
        if rid not in recs:
            throw(f"Ledger entry {rid} does not belong to this account.")
    # selections may replace pending suggestions, never confirmed matches
    for sid in line_ids:
        if lines[sid]["status"] == "Matched":
            throw(f"Bank line {sid} is already matched. Unmatch it first.")
    for rid in record_ids:
        m = taken.get(rid)
        if m and m["status"] == "Confirmed":
            throw(f"Ledger entry {rid} is already matched. Unmatch it first.")
    for sid in line_ids:
        if lines[sid]["status"] == "Suggested":
            _release(_group_rows(lines[sid]["match_group"]))
    for rid in record_ids:
        m = taken.get(rid)
        if m and m["status"] == "Suggested":
            try:
                _release(_group_rows(m["match_group"]))
            except Exception:
                pass
    sl = {sid: _line_item(lines[sid]) for sid in line_ids}
    sr = {rid: recs[rid] for rid in record_ids}
    net = sum((x["signed"] for x in sl.values()), Decimal(0)) - sum((x["signed"] for x in sr.values()), Decimal(0))
    if abs(net) > Decimal("0.005"):
        throw(f"The selection is not balanced: the bank side differs from the ledger side by {abs(net):,.2f}. Match items that add up to the same amount.")
    g = engine.Group(list(line_ids), list(record_ids), "Manual", 100.0, reason or "Matched manually by a user")
    _save_group(b, g, "Confirmed", sl, sr)
    return {"lines": len(line_ids), "records": len(record_ids)}


def ignore_lines(line_ids: list[str], reason: str) -> int:
    if not (reason or "").strip():
        throw("Give a reason for ignoring a bank line (for example: duplicate of another line).")
    for lid in line_ids:
        l = get_doc("Bank Statement Line", lid, ignore_permissions=True)
        if l.reconciliation or l.status in ("Matched",):
            throw(f"Bank line {lid} is matched or locked and cannot be ignored.")
        if l.status == "Suggested":
            _release(_group_rows(l.match_group))
            l.reload()
        l.status = "Ignored"; l.ignore_reason = reason.strip()
        l.save(ignore_permissions=True)
    return len(line_ids)


def restore_lines(line_ids: list[str]) -> int:
    for lid in line_ids:
        l = get_doc("Bank Statement Line", lid, ignore_permissions=True)
        if l.status == "Ignored":
            l.status = "Unmatched"; l.ignore_reason = None
            l.save(ignore_permissions=True)
    return len(line_ids)


def clear_opening_entries(bank_account: str, before_date) -> dict:
    """Mark every open ledger entry before ``before_date`` as already reconciled (go-live cut-off)."""
    b = bank(bank_account)
    cutoff = _d(before_date)
    taken = {m["ledger_record"] for m in matches_of(b.name) if m["ledger_record"]}
    todo = [r for r in ledger_records(b, cutoff) if r["id"] not in taken and r["date"] < cutoff]
    gid = _new_group()
    for r in todo:
        new_doc("Bank Reconciliation Match", bank_account=b.name, match_group=gid, ledger_record=r["id"], signed_amount=r["signed"], status="Confirmed",
                method="Manual", confidence=100, reason=f"Opening clearance: assumed reconciled before {cutoff}").insert(ignore_permissions=True)
    return {"cleared": len(todo), "net": str(sum((r["signed"] for r in todo), Decimal(0)))}


# ------------------------------------------------------------------------------------------------------------ reconciliation
def compute(bank_account: str, from_date, to_date, opening=None, closing=None) -> dict:
    """The reconciliation statement for one bank account as at ``to_date``."""
    b = bank(bank_account)
    to_d, from_d = _d(to_date), _d(from_date)
    if not to_d:
        throw("Choose the date to reconcile up to.")
    lines = [l for l in lines_of(b, to_d) if l["status"] != "Ignored"]
    recs = ledger_records(b, to_d)
    confirmed = matches_of(b.name, ("Confirmed",))
    line_date = {l["name"]: _d(l["posting_date"]) for l in get_list("Bank Statement Line", filters=[["bank_account", "=", b.name]], fields=["name", "posting_date"], limit=500000, ignore_permissions=True)}
    rec_date = {r["id"]: r["date"] for r in ledger_records(b)}
    members: dict = {}
    for m in confirmed:
        members.setdefault(m["match_group"], []).append(m)
    cleared_lines, cleared_recs, cleared_groups = set(), set(), []
    for gid, ms in members.items():
        dates = [line_date.get(m["statement_line"]) if m["statement_line"] else rec_date.get(m["ledger_record"]) for m in ms]
        if dates and all(d and d <= to_d for d in dates):
            cleared_groups.append(gid)
            for m in ms:
                (cleared_lines if m["statement_line"] else cleared_recs).add(m["statement_line"] or m["ledger_record"])
    open_lines = [l for l in lines if l["name"] not in cleared_lines]
    open_recs = [r for r in recs if r["id"] not in cleared_recs]
    suggested_groups = {m["match_group"] for m in matches_of(b.name, ("Suggested",))}
    ledger_balance = sum((r["signed"] for r in recs), Decimal(0))
    sgn = lambda l: D(l["amount"]) if l["direction"] == "Receipt" else -D(l["amount"])
    dit = sum((r["signed"] for r in open_recs if r["signed"] > 0), Decimal(0))
    outp = -sum((r["signed"] for r in open_recs if r["signed"] < 0), Decimal(0))
    urr = sum((sgn(l) for l in open_lines if sgn(l) > 0), Decimal(0))
    urp = -sum((sgn(l) for l in open_lines if sgn(l) < 0), Decimal(0))
    closing_d = D(closing)
    adj_bank = closing_d + dit - outp
    adj_book = ledger_balance + urr - urp
    in_period = [l for l in get_list("Bank Statement Line", filters=[["bank_account", "=", b.name], ["posting_date", "<=", str(to_d)]] + ([["posting_date", ">=", str(from_d)]] if from_d else []),
                                     fields=["name", "direction", "amount", "status"], limit=200000, ignore_permissions=True)]
    net_period = sum((sgn(l) for l in in_period), Decimal(0))
    pending_review = len([l for l in in_period if l["status"] == "Suggested"])
    matched = len([l for l in in_period if l["name"] in cleared_lines])
    unmatched = len([l for l in in_period if l["status"] == "Unmatched"])
    items = []
    for r in open_recs:
        items.append({"category": "Deposit in Transit" if r["signed"] > 0 else "Outstanding Payment", "item_date": r["date"], "reference": r.get("reference"), "description": r.get("text") or r.get("party") or "", "amount": abs(r["signed"]), "source": r["id"]})
    for l in open_lines:
        s = sgn(l)
        items.append({"category": "Unrecorded Bank Receipt" if s > 0 else "Unrecorded Bank Payment", "item_date": _d(l["posting_date"]), "reference": l.get("reference"), "description": l.get("description") or "", "amount": abs(s), "source": l["name"]})
    variance = (adj_bank - adj_book)
    return {"gl_account": b.gl_account, "currency": _cur(b), "ledger_balance": ledger_balance, "deposits_in_transit": dit, "outstanding_payments": outp,
            "adjusted_bank_balance": adj_bank, "unrecorded_receipts": urr, "unrecorded_payments": urp, "adjusted_book_balance": adj_book, "variance": variance,
            "statement_check": (D(opening) + net_period - closing_d) if opening is not None and closing is not None else 0,
            "statement_lines_total": len(in_period), "matched_lines": matched, "suggested_lines": pending_review, "unmatched_lines": unmatched,
            "match_rate": round(100 * matched / len(in_period), 1) if in_period else 0, "items": items,
            "cleared_group_ids": cleared_groups,
            "suggested_group_count": len(suggested_groups)}


def lock(reconciliation: str, bank_account: str, cleared_groups: list[str], on: bool) -> None:
    for gid in cleared_groups:
        for m in _group_rows(gid):
            doc = get_doc("Bank Reconciliation Match", m["name"], ignore_permissions=True)
            doc.reconciliation = reconciliation if on else None
            doc.save(ignore_permissions=True)
            if m["statement_line"]:
                _set_line(m["statement_line"], reconciliation=reconciliation if on else None)


# ---------------------------------------------------------------------------------------------------------- workbench data
def workbench(bank_account: str, to_date=None) -> dict:
    b = bank(bank_account)
    to_d = _d(to_date) or date.today()
    all_lines = lines_of(b)
    all_m = matches_of(b.name)
    recs = {r["id"]: r for r in ledger_records(b)}
    taken = {m["ledger_record"] for m in all_m if m["ledger_record"]}
    groups: dict = {}
    for m in all_m:
        groups.setdefault(m["match_group"], []).append(m)
    ln = {l["name"]: l for l in all_lines}

    def line_view(l):
        return {"id": l["name"], "date": str(l["posting_date"]), "direction": l["direction"], "amount": str(D(l["amount"])), "description": l.get("description"), "reference": l.get("reference"),
                "status": l["status"], "proposed_account": l.get("proposed_account"), "posting_batch": l.get("posting_batch"), "ignore_reason": l.get("ignore_reason")}

    def rec_view(r):
        return {"id": r["id"], "date": str(r["date"]), "signed": str(r["signed"]), "reference": r.get("reference"), "description": r.get("text"), "party": r.get("party"), "source": f"{r.get('source_doctype') or ''} {r.get('source_name') or ''}".strip()}

    suggestions, matched = [], []
    for gid, ms in groups.items():
        entry = {"group": gid, "method": ms[0]["method"], "confidence": float(ms[0]["confidence"] or 0), "reason": ms[0]["reason"], "status": ms[0]["status"],
                 "locked": bool(ms[0].get("reconciliation")),
                 "lines": [line_view(ln[m["statement_line"]]) for m in ms if m["statement_line"] and m["statement_line"] in ln],
                 "records": [rec_view(recs[m["ledger_record"]]) for m in ms if m["ledger_record"] and m["ledger_record"] in recs]}
        (suggestions if ms[0]["status"] == "Suggested" else matched).append(entry)
    suggestions.sort(key=lambda g: -g["confidence"])
    matched.sort(key=lambda g: (g["lines"][0]["date"] if g["lines"] else (g["records"][0]["date"] if g["records"] else "")), reverse=True)
    return {"bank_account": b.name, "gl_account": b.gl_account, "currency": _cur(b),
            "settings": {"auto_accept_threshold": float(b.auto_accept_threshold or 90), "date_tolerance_days": int(b.date_tolerance_days if b.date_tolerance_days is not None else 4), "auto_reconcile": bool(b.auto_reconcile), "auto_post_coded": bool(b.auto_post_coded)},
            "unmatched_lines": [line_view(l) for l in all_lines if l["status"] == "Unmatched"],
            "ignored_lines": [line_view(l) for l in all_lines if l["status"] == "Ignored"],
            "unmatched_records": [rec_view(r) for rid, r in recs.items() if rid not in taken and r["date"] <= to_d],
            "suggestions": suggestions, "matched": matched[:300], "matched_total": len(matched),
            "ledger_balance": str(sum((r["signed"] for r in recs.values() if r["date"] <= to_d), Decimal(0))),
            "last_line_date": str(max((_d(l["posting_date"]) for l in all_lines), default="") or ""), "last_closing_balance": None}


# ----------------------------------------------------------------------------------------------------------- scheduler
def run_scheduled_reconciliation():
    """Hourly: for every bank account set to reconcile automatically, match anything new."""
    done = 0
    for row in get_list("Bank Account", filters={"auto_reconcile": 1, "disabled": 0}, fields=["name"], limit=1000, ignore_permissions=True):
        try:
            run_auto(row["name"])
            done += 1
        except Exception:                                                # one account's problem must not stop the others
            import logging
            logging.getLogger("velora_erp.bank").exception("Automatic bank reconciliation failed for %s", row["name"])
    return done
