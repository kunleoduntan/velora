"""Permission-aware global search. Uses the optional search index when installed and a bounded metadata fallback otherwise."""
from __future__ import annotations

import re
import time
import unicodedata

from fastapi import FastAPI, Request

from ..exceptions import DoesNotExistError, PermissionDenied, VeloraError
from ..meta.registry import registry
from ..document import get_list
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


def search_link(doctype: str, txt: str = "", filters=None, limit: int = 10) -> list[dict]:
    """Options for a Link field, the way Frappe's search_link gives them: only what the user may read, the field's own
    filters applied, disabled records left out, best match first, with a short description beside the ID."""
    meta = registry.get(doctype)
    if not has_permission(meta, "read"):
        raise PermissionDenied(f"You may not read {doctype}")
    limit = max(1, min(int(limit or 10), 50))
    flt = [list(f) for f in (filters or []) if isinstance(f, (list, tuple)) and len(f) == 3]
    if meta.get_field("disabled") and not any(f[0] == "disabled" for f in flt):
        flt.append(["disabled", "=", 0])
    txt = " ".join((txt or "").split())[:100]
    if txt:
        flt.append(["_search", "like", txt])
    title = meta.title_field if meta.title_field and meta.title_field != "name" and meta.get_field(meta.title_field) else None
    if not title:
        title = next((f.fieldname for f in meta.fields if f.fieldname.endswith("_name") and f.fieldtype == "Data" and not f.hidden), None)
    extra = [f.fieldname for f in meta.fields if f.fieldname != title and f.has_column and not f.hidden and f.fieldtype in ("Data", "Select", "Link")
             and (f.in_list_view or f.in_standard_filter)][:2]
    fields = ["name", *([title] if title else []), *extra]
    rows = get_list(doctype, filters=flt, fields=fields, order_by="modified desc", limit=max(limit * 6, 60))
    rows.sort(key=lambda r: _rank(txt, str(r["name"]), str(r.get(title) or "") if title else ""))
    out = []
    for r in rows[:limit]:
        bits = [str(r[k]) for k in ([title] if title else []) + extra if r.get(k) not in (None, "") and str(r[k]) != str(r["name"])]
        out.append({"name": str(r["name"]), "title": str(r.get(title) or "") if title else "", "description": " · ".join(bits[:3])})
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
