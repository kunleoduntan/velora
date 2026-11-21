"""Bank matching engine: pairs bank statement lines with ledger entries. Pure functions, no database.

Statement items:  {id, date, signed, reference, description, counterparty}
Ledger items:     {id, date, signed, refs: [str], text: str, party}
``signed`` is positive for money in (a receipt) and negative for money out (a payment), the same on both sides, so a match is
simply "the same signed amount".

The engine runs in passes, strongest evidence first, and every group it returns carries a confidence (0-100), the method used and a
plain-language reason so a reviewer can see *why*:

 2. One-to-one       - candidate pairs with equal amounts are scored on reference, date and wording, then assigned greedily from the
                       best score down so one weak pair can never steal a record from a stronger one. A reference that appears on
                       both sides is near-certain; an amount that has exactly one possible counterpart is strong; an amount with
                       several possible counterparts needs wording evidence to be auto-confirmed.
 3. Combined         - one bank line that equals the sum of several ledger entries (a banked batch of receipts), or several bank lines
                       that equal one ledger entry (a payment the bank split).
 4. Statement pairs  - a bank line and its own reversal (same reference, opposite direction).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import combinations

STOP = {"LTD", "PLC", "LIMITED", "NIG", "NIGERIA", "NIGERIAN", "AND", "THE", "OF", "CO", "COMPANY", "INC", "LLC", "PAYMENT", "TRANSFER", "TRF", "NIP",
        "FROM", "TO", "FOR", "BY", "INWARD", "OUTWARD", "WEB", "POS", "ATM", "REF", "NO", "NUMBER", "CHARGE"}
ABBREV = {"GTB": "GUARANTY TRUST", "GTBANK": "GUARANTY TRUST", "FBN": "FIRST BANK", "UBA": "UNITED BANK AFRICA", "FCMB": "FIRST CITY MONUMENT",
          "STERLING": "STERLING", "PENCOM": "PENSION COMMISSION", "FIRS": "FEDERAL INLAND REVENUE", "VAT": "VALUE ADDED TAX", "WHT": "WITHHOLDING TAX"}
CENT = Decimal("0.01")


def money(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(CENT)


def norm_ref(text) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def tokens(text) -> set[str]:
    t = re.sub(r"[^A-Z0-9 ]", " ", str(text or "").upper())
    out: set[str] = set()
    for w in t.split():
        w = ABBREV.get(w, w)
        for p in w.split():
            if p not in STOP and len(p) > 1:
                out.add(p)
    return out


def similarity(a, b) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    contain = (len(ta & tb) / min(len(ta), len(tb))) * 0.9
    seq = difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio() * 0.9
    return round(max(jac, contain, seq), 4)


@dataclass
class Group:
    lines: list[str]
    records: list[str]
    method: str
    confidence: float
    reason: str
    members: dict = field(default_factory=dict)


def _days(a, b) -> int:
    return abs((a - b).days)


def _ref_hit(line: dict, rec: dict) -> str | None:
    """The shared reference between a statement line and a ledger entry, if any (>= 4 chars after normalising)."""
    ldesc = norm_ref(line.get("description"))
    for lref in [norm_ref(line.get("reference"))] + [norm_ref(a) for a in line.get("aliases", [])]:
        hit = _ref_hit_one(line, rec, lref, ldesc)
        if hit:
            return hit
    return None


def _ref_hit_one(line, rec, lref, ldesc):
    for r in rec.get("refs", []):
        nr = norm_ref(r)
        if len(nr) < 4:
            continue
        if lref and (nr == lref or (len(lref) >= 5 and (nr in lref or lref in nr))):
            return r
        if len(nr) >= 6 and nr in ldesc:
            return r
    if len(lref) >= 6:
        rtext = norm_ref(rec.get("text"))
        if lref in rtext:
            return line.get("reference")
    return None


def _text(line: dict) -> str:
    return " ".join(str(line.get(k) or "") for k in ("counterparty", "description", "reference"))


def _rtext(rec: dict) -> str:
    return " ".join([str(rec.get("text") or ""), str(rec.get("party") or "")] + [str(r) for r in rec.get("refs", [])])


def match(statement: list[dict], ledger: list[dict], *, date_tolerance: int = 4, amount_tolerance: Decimal | float = 0,
          max_combo: int = 5, auto_accept: float = 90.0, excluded: set | None = None) -> list[Group]:
    excluded = excluded or set()
    amount_tol = money(amount_tolerance)
    sl = {s["id"]: {**s, "signed": money(s["signed"])} for s in statement}
    gl = {g["id"]: {**g, "signed": money(g["signed"])} for g in ledger}
    groups: list[Group] = []

    # 2 -- one-to-one -------------------------------------------------------------------------------------------------
    window = max(date_tolerance * 3, 14)
    cands: dict[tuple[str, str], dict] = {}
    by_line: dict[str, list[str]] = {}
    by_rec: dict[str, list[str]] = {}
    for sid, s in sl.items():
        for gid, g in gl.items():
            if (sid, gid) in excluded:
                continue
            diff = abs(s["signed"] - g["signed"])
            exact = diff == 0
            if not exact and not (amount_tol and diff <= amount_tol and (s["signed"] > 0) == (g["signed"] > 0)):
                continue
            d = _days(s["date"], g["date"])
            ref = _ref_hit(s, g)
            if d > window and not (ref and exact):
                continue
            cands[(sid, gid)] = {"diff": diff, "days": d, "ref": ref, "text": similarity(_text(s), _rtext(g))}
            by_line.setdefault(sid, []).append(gid)
            by_rec.setdefault(gid, []).append(sid)
    scored = []
    for (sid, gid), c in cands.items():
        exact = c["diff"] == 0
        date_score = max(0.0, 1.0 - c["days"] / (window + 1))
        in_tol = c["days"] <= date_tolerance
        unique = len(by_line[sid]) == 1 and len(by_rec[gid]) == 1
        if c["ref"] and exact:
            conf = 90 + 10 * (0.6 * date_score + 0.4 * c["text"])
            method, why = "Reference", f"Reference {c['ref']!s} appears on both sides with the same amount"
        elif not exact:
            conf = min(80.0, 50 + 20 * date_score + 10 * c["text"] - 20 * float(c["diff"] / max(amount_tol, CENT)) / 2)
            method, why = "Scored", f"Amounts differ by {c['diff']}, within the allowed tolerance"
        elif unique and in_tol:
            conf = 88 + 7 * date_score + 5 * c["text"]
            method, why = "Exact Amount", "The only ledger entry with this exact amount near this date" if c["text"] < 0.3 else "The only ledger entry with this exact amount near this date, and the wording agrees"
        else:
            conf = 100 * (0.55 + 0.25 * date_score + 0.20 * c["text"]) if in_tol else 100 * (0.40 + 0.15 * date_score + 0.15 * c["text"])
            method, why = "Scored", "Same amount; chosen on date and wording because several entries share this amount"
        if c["ref"] is None and exact and not unique:
            rivals = sorted((x for x in (cands[(sid, g2)] for g2 in by_line[sid]) if x is not c), key=lambda x: -(x["text"] + 0.0))
            # several equal-amount entries: only wording that clearly favours this one may lift it into auto-accept range
            if c["text"] < 0.5 or (rivals and rivals[0]["text"] >= c["text"] - 0.15):
                conf = min(conf, auto_accept - 5.5)
        if c["days"] > date_tolerance:
            why += f"; dates are {c['days']} days apart"
            conf = min(conf, auto_accept - 1 if c["ref"] else auto_accept - 5)
        scored.append((conf, -c["days"], sid, gid, method, why))
    scored.sort(key=lambda r: (-r[0], r[1], r[2], r[3]))
    used_s, used_g = set(), set()
    for conf, _, sid, gid, method, why in scored:
        if sid in used_s or gid in used_g:
            continue
        used_s.add(sid); used_g.add(gid)
        groups.append(Group([sid], [gid], method, round(min(conf, 100.0), 1), why))
    for sid in used_s:
        sl.pop(sid, None)
    for gid in used_g:
        gl.pop(gid, None)

    # 3 -- combined (one-to-many) --------------------------------------------------------------------------------------
    groups += _combined(sl, gl, date_tolerance, window, max_combo, auto_accept)

    # 4 -- statement reversal pairs ----------------------------------------------------------------------------------------
    items = sorted(sl.values(), key=lambda s: s["date"])
    for i, a in enumerate(items):
        if a["id"] not in sl:
            continue
        ra = norm_ref(a.get("reference"))
        if len(ra) < 4:
            continue
        for b in items[i + 1:]:
            if b["id"] in sl and b["signed"] == -a["signed"] and norm_ref(b.get("reference")) == ra and _days(a["date"], b["date"]) <= 10:
                groups.append(Group([a["id"], b["id"]], [], "Statement Reversal", 95.0, f"The bank line and its reversal share reference {a.get('reference')} and cancel out"))
                sl.pop(a["id"], None); sl.pop(b["id"], None)
                break
    return groups


def _combined(sl, gl, tol, window, max_combo, auto_accept) -> list[Group]:
    out: list[Group] = []
    budget = [200_000]

    def subsets(target: Decimal, pool: list[dict], key: str):
        """All subsets (size 2..max_combo) of pool whose signed amounts sum to target; stops after budget is spent."""
        found = []
        pool = sorted(pool, key=lambda r: r["signed"])
        for size in range(2, max_combo + 1):
            for combo in combinations(pool, size):
                budget[0] -= 1
                if budget[0] <= 0:
                    return found
                if sum((c["signed"] for c in combo), Decimal(0)) == target:
                    found.append(combo)
                    if len(found) > 3:
                        return found
        return found

    # one bank line = several ledger entries
    for sid, s in sorted(sl.items(), key=lambda kv: kv[1]["date"]):
        if sid not in sl:
            continue
        pool = [g for g in gl.values() if (g["signed"] > 0) == (s["signed"] > 0) and abs(g["signed"]) < abs(s["signed"]) and _days(g["date"], s["date"]) <= window][:22]
        if len(pool) < 2:
            continue
        found = subsets(s["signed"], pool, "g")
        if not found:
            continue
        combo = found[0]
        parties = {c.get("party") for c in combo if c.get("party")}
        tight = all(_days(c["date"], s["date"]) <= tol for c in combo)
        conf = 78 + (6 if len(parties) == 1 else 0) + (6 if tight else 0) + 8 * similarity(_text(s), " ".join(_rtext(c) for c in combo))
        if len(found) > 1:
            conf = min(conf, auto_accept - 10)
        out.append(Group([sid], [c["id"] for c in combo], "Split / Combined", round(min(conf, 95.0), 1),
                         f"One bank line equals the sum of {len(combo)} ledger entries" + (" (other combinations also fit; please review)" if len(found) > 1 else "")))
        sl.pop(sid, None)
        for c in combo:
            gl.pop(c["id"], None)
    # several bank lines = one ledger entry
    for gid, g in sorted(gl.items(), key=lambda kv: kv[1]["date"]):
        if gid not in gl:
            continue
        pool = [s for s in sl.values() if (s["signed"] > 0) == (g["signed"] > 0) and abs(s["signed"]) < abs(g["signed"]) and _days(s["date"], g["date"]) <= window][:22]
        if len(pool) < 2:
            continue
        found = subsets(g["signed"], pool, "s")
        if not found:
            continue
        combo = found[0]
        tight = all(_days(c["date"], g["date"]) <= tol for c in combo)
        conf = 78 + (6 if tight else 0) + 8 * similarity(_rtext(g), " ".join(_text(c) for c in combo))
        if len(found) > 1:
            conf = min(conf, auto_accept - 10)
        out.append(Group([c["id"] for c in combo], [gid], "Split / Combined", round(min(conf, 95.0), 1), f"{len(combo)} bank lines add up to one ledger entry"))
        gl.pop(gid, None)
        for c in combo:
            sl.pop(c["id"], None)
    return out
