"""Permission-aware global search. Uses the optional search index when installed and a bounded metadata fallback otherwise."""
from __future__ import annotations

import re
import time
import unicodedata

from fastapi import FastAPI, Request

from ..exceptions import DoesNotExistError, PermissionDenied, VeloraError
from ..meta.registry import registry
from ..document import get_list
from ..db.tables import get_table
from ..permissions import field_access, has_permission

SEARCHABLE_TYPES = {"Data", "Text", "Small Text", "Long Text", "Link", "Select", "Email", "Phone", "Code", "Int", "Float", "Currency", "Date", "Datetime"}
SENSITIVE_FIELD = re.compile(r"pass(word)?|secret|token|api_?key|private_?key|otp|pin$", re.I)


BUDGET_SECONDS = 2.5      # total time the metadata fallback may spend; partial results are returned instead of a timeout
ROWS_PER_DOCTYPE = 200
FIELDS_PER_DOCTYPE = 12


def _fallback_query(q: str, limit: int, doctype: str | None = None):
    raw = " ".join((q or "").split())[:100]
    tokens = re.findall(r"[^\W_]+", unicodedata.normalize("NFKD", raw).casefold())
    tokens = ["".join(ch for ch in token if not unicodedata.combining(ch)) for token in tokens]
    if not tokens or len(raw) < 2:
        return []
    limit = max(1, min(int(limit or 12), 50))
    metas = [registry.get(doctype)] if doctype else sorted(registry.all(), key=lambda m: (not m.title_field, m.module, m.name))
    hits = []
    deadline = time.monotonic() + BUDGET_SECONDS
    anchor = max(tokens, key=len)
    # Bound the work per DocType. Each query still goes through get_list, which
    # enforces read permissions, row policies and field-level visibility.
    for meta in metas:
        if len(hits) >= limit or time.monotonic() > deadline:
            break
        if meta.istable or not has_permission(meta, "read"):
            continue
        candidates = [f for f in meta.fields if f.fieldtype in SEARCHABLE_TYPES and not f.hidden
                      and not SENSITIVE_FIELD.search(f.fieldname) and field_access(meta.name, f.fieldname) != "hidden"]
        title_field = meta.title_field if meta.title_field and meta.get_field(meta.title_field) and field_access(meta.name, meta.title_field) != "hidden" else None
        if title_field and SENSITIVE_FIELD.search(title_field):
            title_field = None
        # Prioritise fields users expect to search, but cover a broad set of
        # metadata fields instead of silently ignoring everything after field 10.
        candidates.sort(key=lambda f: (not bool(getattr(f, "in_list_view", False)), not bool(getattr(f, "required", False)), f.fieldname))
        searchable = candidates[:FIELDS_PER_DOCTYPE]
        fields = list(dict.fromkeys(["name"] + ([title_field] if title_field else []) + [f.fieldname for f in searchable]))
        try:
            # One query per doctype over name, title and every readable text column (case-insensitive, every word must match):
            # it finds old records too, not only the most recent few hundred. get_list still enforces permissions and row policies.
            rows = get_list(meta.name, filters=[["_search", "like", raw]], fields=fields, order_by="modified desc", limit=max(limit, 20))
        except (PermissionDenied, DoesNotExistError):
            continue
        except VeloraError:
            continue
        for row in rows:
            name = str(row.get("name") or "")
            title = str(row.get(title_field) or name) if title_field else name
            values = [name, title] + [str(row.get(f.fieldname) or "") for f in searchable]
            haystack = unicodedata.normalize("NFKD", " ".join(values)).casefold()
            haystack = "".join(ch for ch in haystack if not unicodedata.combining(ch))
            if all(token in haystack for token in tokens):
                hits.append({"doctype": meta.name, "name": name, "title": title})
                if len(hits) >= limit:
                    break
    return hits


def _rank(txt: str, name: str, title: str) -> tuple:
    """Frappe's search_link ordering: exact match, then 'starts with', then 'contains', each shorter-first."""
    t, n, ti = txt.casefold(), name.casefold(), (title or "").casefold()
    if not t:
        return (5, 0, n)
    if n == t:
        return (0, len(n), n)
    if n.startswith(t):
        return (1, len(n), n)
    if ti.startswith(t):
        return (2, len(ti), n)
    pos = min([p for p in (n.find(t), ti.find(t)) if p >= 0] or [99])
    return (3 + (pos > 0) * 0.5, pos, n) if pos < 99 else (4, len(n), n)


def _may_pick(doctype: str) -> bool:
    """True when the user may create or edit a document that holds a Link to `doctype` (directly or through a child table)."""
    for owner, _field in registry.links_to(doctype):
        holders = [owner]
        if owner.istable:
            holders = [d for d in registry.all() if any(f.fieldtype == "Table" and f.options == owner.name for f in d.fields)]
        if any(has_permission(h, "write") or has_permission(h, "create") for h in holders):
            return True
    return False


def search_link(doctype: str, txt: str = "", filters=None, limit: int = 10) -> list[dict]:
    """Fast, permission-aware Link autocomplete.

    Search only the record key and configured title/list columns. The global
    search `_search` predicate intentionally scans a broad set of fields and
    is therefore unsuitable for a keystroke-driven Link lookup.
    """
    meta = registry.get(doctype)
    # A master (Business Unit, Currency, Cost Centre ...) may be picked from a Link field by anyone who can fill in a document that
    # links to it, even when their role cannot open the master's own list (Frappe's "select" permission). Only the key and the
    # title/list columns come back.
    picking = not has_permission(meta, "read")
    if picking and not _may_pick(doctype):
        raise PermissionDenied(f"You may not read {doctype}")
    limit = max(1, min(int(limit or 10), 50))
    # Like Frappe and Dynamics, a lookup on a master (not a submittable document, no row policy for this user) does one role check
    # and then a single plain query: only the key and the title/list columns come back, so the per-record checks add nothing.
    from ..permissions import row_policy_sql
    master = picking or (not meta.is_submittable and row_policy_sql(doctype, "read", get_table(doctype)) is None)
    def _list(*args, **kwargs):
        return get_list(*args, ignore_permissions=master, **kwargs)
    def visible(fieldname):
        return picking or field_access(doctype, fieldname) != "hidden"
    flt = [list(f) for f in (filters or []) if isinstance(f, (list, tuple)) and len(f) == 3]
    if meta.get_field("disabled") and not any(f[0] == "disabled" for f in flt):
        flt.append(["disabled", "=", 0])

    title = meta.title_field if meta.title_field and meta.title_field != "name" and meta.get_field(meta.title_field) and visible(meta.title_field) else None
    if not title:
        title = next((f.fieldname for f in meta.fields if f.fieldname.endswith("_name") and f.fieldtype == "Data" and not f.hidden), None)
    extra = [f.fieldname for f in meta.fields
             if f.fieldname not in ("name", title) and f.has_column and not f.hidden
             and f.fieldtype in ("Data", "Select", "Link")
             and (f.in_list_view or f.in_standard_filter)
             and visible(f.fieldname)][:2]
    fields = ["name", *([title] if title else []), *extra]
    query = " ".join((txt or "").split())[:100]

    # A blank lookup shows the latest permitted options. For typed lookups,
    # exact and prefix matches are fetched first; contains matches are only
    # queried when needed. Every query goes through get_list, so role, row,
    # sharing and User Permission scopes remain in force.
    rows_by_name = {}
    if not query:
        rows = _list(doctype, filters=flt, fields=fields, order_by="name asc", limit=limit)
        rows_by_name.update((str(r["name"]), r) for r in rows)
    else:
        fields_to_search = ["name"] + ([title] if title else []) + extra
        # Two queries at most, whatever the number of columns: names that START with the text (an exact match is one of them),
        # then, only if there is still room, names that merely CONTAIN it. Each query ORs the columns together.
        room = max(20, min(limit * 4, 120))
        for pattern in (f"{query}%", f"%{query}%"):
            if len(rows_by_name) >= limit:
                break
            for r in _list(doctype, filters=list(flt) + [["_any", "like", [pattern, fields_to_search]]], fields=fields, order_by="name asc", limit=room):
                rows_by_name.setdefault(str(r["name"]), r)

    rows = list(rows_by_name.values())
    rows.sort(key=lambda r: _rank(query, str(r["name"]), str(r.get(title) or "") if title else ""))
    out = []
    for r in rows[:limit]:
        bits = [str(r[k]) for k in ([title] if title else []) + extra
                if r.get(k) not in (None, "") and str(r[k]) != str(r["name"])]
        out.append({"name": str(r["name"]), "title": str(r.get(title) or "") if title else "",
                    "description": " · ".join(bits[:3])})
    return out


def install_search_routes(app: FastAPI, scope, run):
    @app.get("/api/database/tune")
    def database_tune_preview(request: Request):
        from .. import dbtune
        return run(request, dbtune.preview)

    @app.post("/api/database/tune")
    def database_tune(request: Request):
        from .. import dbtune
        return run(request, dbtune.tune)

    @app.get("/api/search-link")
    def search_link_route(request: Request, doctype: str, txt: str = "", filters: str = "", limit: int = 10):
        import json as _json
        try:
            flt = _json.loads(filters) if filters else []
        except ValueError:
            flt = []
        return run(request, lambda: search_link(doctype, txt, flt, limit))

    @app.get("/api/search")
    def search(request: Request, q: str = "", limit: int = 20, doctype: str = ""):
        def fn():
            if registry.exists("Search Index"):
                try:
                    from velora_search import indexer
                    indexed = indexer.query(q, limit, doctype or None)
                    if indexed:
                        return indexed
                except Exception:  # stale/missing index or unavailable optional package
                    pass
            # A stale or empty index must not make global search appear broken.
            # The fallback is bounded and permission-aware, so users can still
            # find records while an administrator rebuilds the index.
            return _fallback_query(q, limit, doctype or None)
        return run(request, fn)
