"""Global search: keep a small index of every document's title and text, and query it.

What is indexed: the title (the DocType's title field, else the name) and the text of Data/Text/Link/Select fields (never anything that looks like a secret), folded to
lower case without accents ("Ọláolúwa" -> "olaoluwa"), so a search never depends on how someone typed it. Child tables are part of their parent, not indexed on their own.
Results only ever include DocTypes the asking user may read.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from sqlalchemy import and_, delete, insert, select, text

from velora import db
from velora.db.tables import get_table
from velora.document.document import now
from velora.meta.registry import registry
from velora.permissions import has_permission

TEXT_TYPES = {"Data", "Text", "Link", "Select"}
SECRET = re.compile(r"pass(word)?|secret|token|api_?key|private_?key|otp|pin$", re.I)
MAX_BODY, MAX_TOKENS, MAX_QUERY = 2000, 8, 100
SKIP = ("Notification ", "Search Index")


def fold(s) -> str:
    """Lower case, no accents, single spaces."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c)).casefold()).strip()


def words(s) -> str:
    """Index text: folded, and punctuation turned into spaces, so 'info@acme.ng' and 'CUST-0001' are findable by any of their parts
    (PostgreSQL's full-text parser would otherwise keep an email or a hyphenated code as ONE unsearchable-by-prefix token)."""
    return " ".join(re.findall(r"[^\W_]+", fold(s)))


def indexable(meta) -> bool:
    return not meta.istable and not meta.name.startswith(SKIP)


def title_fieldname(meta) -> str | None:
    """The field that names a record: the DocType's title field, else its first list-view text field (so 'Ada Okafor' is shown and typo-searched, not 'C-0001')."""
    if meta.title_field:
        return meta.title_field
    return next((f.fieldname for f in meta.value_fields if f.in_list_view and f.fieldtype == "Data" and not SECRET.search(f.fieldname)), None)


def build(meta, get) -> tuple[str, str, str]:
    """(title, title_norm, body_norm) for one record; `get(fieldname)` reads its values."""
    tf = title_fieldname(meta)
    title = str(get(tf) or "") if tf else ""
    name = str(get("name") or "")
    title = title or name
    parts = [name]
    for f in meta.value_fields:
        if f.fieldtype in TEXT_TYPES and not SECRET.search(f.fieldname) and f.fieldname != tf:
            v = get(f.fieldname)
            if v not in (None, ""):
                parts.append(str(v))
    body = words(" ".join(parts))[:MAX_BODY]
    return title[:255], words(title)[:255], body


def _row_name(doctype: str, docname: str) -> str:
    n = f"{doctype}::{docname}"
    return n if len(n) <= 240 else hashlib.sha1(n.encode()).hexdigest()


def upsert(meta, docname: str, get) -> None:
    t = get_table("Search Index")
    title, tnorm, body = build(meta, get)
    n = now()
    with db.transaction() as c:
        c.execute(delete(t).where(t.c.ref_doctype == meta.name, t.c.ref_name == docname))
        c.execute(insert(t).values(name=_row_name(meta.name, docname), owner="Search", creation=n, modified=n, modified_by="Search", docstatus=0, idx=0, ref_doctype=meta.name,
                                   ref_name=docname, title=title, title_norm=tnorm, body_norm=body))


def remove(doctype: str, docname: str) -> None:
    t = get_table("Search Index")
    with db.transaction() as c:
        c.execute(delete(t).where(t.c.ref_doctype == doctype, t.c.ref_name == docname))


def on_save(doc) -> None:
    meta = registry.get(doc.doctype)
    if not indexable(meta):
        return
    if int(doc.docstatus or 0) == 2:
        return remove(doc.doctype, doc.name)
    try:
        with db.conn().begin_nested():                        # a problem indexing must never fail the save
            upsert(meta, doc.name, doc.get)
    except Exception:  # noqa: BLE001
        pass


def on_remove(doc) -> None:
    if indexable(registry.get(doc.doctype)):
        remove(doc.doctype, doc.name)


def reindex(doctype: str | None = None, batch: int = 500) -> int:
    """Rebuild the index from the data (after install, or if it ever drifts). Returns the number of documents indexed."""
    n = 0
    for meta in registry.all():
        if not indexable(meta) or (doctype and meta.name != doctype):
            continue
        t = get_table(meta.name)
        cols = set(meta.column_names())
        with db.transaction() as c:
            c.execute(delete(get_table("Search Index")).where(get_table("Search Index").c.ref_doctype == meta.name))
        last = None
        while True:
            q = select(t).order_by(t.c.name).limit(batch)
            if last is not None:
                q = q.where(t.c.name > last)
            if "docstatus" in cols:
                q = q.where(t.c.docstatus < 2)
            with db.transaction() as c:
                rows = [dict(r) for r in c.execute(q).mappings()]
            for r in rows:
                upsert(meta, r["name"], r.get)
                n += 1
            if len(rows) < batch:
                break
            last = rows[-1]["name"]
    return n


def reindex_all() -> None:
    """after_install hook."""
    reindex()


def readable_doctypes() -> list[str]:
    return [m.name for m in registry.all() if indexable(m) and has_permission(m, "read")]


def _like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_scopes(allowed: list[str]) -> dict:
    """{doctype: (table, SQL predicate)} for the DocTypes the user may read only PART of (a row-level policy applies). Empty for most users."""
    from velora.permissions import row_policy_sql
    out = {}
    for d in allowed:
        try:
            t = get_table(d)
        except Exception:  # noqa: BLE001 - a DocType without a table has nothing to scope
            continue
        scope = row_policy_sql(d, "read", t)
        if scope is not None:
            out[d] = (t, scope)
    return out


def _within_scope(c, hits: list[dict], scopes: dict) -> list[dict]:
    """Keep the hits the user's row policy allows. The search index knows titles of EVERY record; without this a user limited to their own branch would still see the titles of the others."""
    if not scopes:
        return hits
    keep = set()
    for d, (t, scope) in scopes.items():
        names = [h["name"] for h in hits if h["doctype"] == d]
        if names:
            keep |= {(d, n) for n in c.execute(select(t.c.name).where(t.c.name.in_(names), scope)).scalars()}
    return [h for h in hits if h["doctype"] not in scopes or (h["doctype"], h["name"]) in keep]


def _page(c, tier, tokens, qn, allowed, off, size):
    """One page of ranked hits. On PostgreSQL `tier` is 1 (every word is a word-start) or 2 (a close misspelling also matches); decided on the first page and kept for the rest."""
    t = get_table("Search Index")
    if c.dialect.name == "postgresql":
        params = {"qn": qn, "prefix": _like(qn) + "%", "allowed": allowed, "lim": size, "off": off, "all": " & ".join(f"{tok}:*" for tok in tokens)}
        select_sql = """
            SELECT ref_doctype, ref_name, title, (ts_rank(tsv, to_tsquery('simple', :all)) + 2 * word_similarity(:qn, title_norm)
                   + CASE WHEN title_norm = :qn THEN 3 WHEN title_norm LIKE :prefix THEN 1 ELSE 0 END) AS rank
            FROM tab_search_index WHERE ref_doctype = ANY(:allowed) AND ({cond}) ORDER BY rank DESC, title, ref_name LIMIT :lim OFFSET :off"""
        if tier in (None, 1):
            rows = c.execute(text(select_sql.format(cond="tsv @@ to_tsquery('simple', :all)")), params).mappings().all()
            if rows or off > 0:
                return rows, 1
        c.exec_driver_sql("SELECT set_config('pg_trgm.word_similarity_threshold', '0.4', true)")        # this transaction only
        conds = []
        for i, tok in enumerate(tokens):
            params[f"t{i}"], params[f"w{i}"] = f"{tok}:*", tok
            conds.append(f"(tsv @@ to_tsquery('simple', :t{i}) OR :w{i} <% title_norm)")
        return c.execute(text(select_sql.format(cond=" AND ".join(conds))), params).mappings().all(), 2
    hay = t.c.title_norm + " " + t.c.body_norm
    conds = [hay.like(f"%{_like(tok)}%", escape="\\") for tok in tokens]
    rank = (t.c.title_norm == qn).desc(), t.c.title_norm.like(f"{_like(qn)}%", escape="\\").desc(), t.c.title, t.c.ref_name
    return c.execute(select(t.c.ref_doctype, t.c.ref_name, t.c.title).where(and_(t.c.ref_doctype.in_(allowed), *conds)).order_by(*rank).limit(size).offset(off)).mappings().all(), 1


def query(q: str, limit: int = 20, doctype: str | None = None) -> list[dict]:
    """Best matches first. Every word must match (as a prefix) in the title or text; on PostgreSQL a close misspelling of a title also matches. Only records the user may read: the
    DocType permission AND any row-level policy."""
    tokens = re.findall(r"[^\W_]+", fold(q)[:MAX_QUERY])[:MAX_TOKENS]
    if not tokens:
        return []
    qn = " ".join(tokens)
    allowed = readable_doctypes()
    if doctype:
        allowed = [d for d in allowed if d == doctype]
    if not allowed:
        return []
    limit = min(max(int(limit), 1), 50)
    scopes = _row_scopes(allowed)
    size = min(limit * 4, 200) if scopes else limit
    out, off, tier = [], 0, None
    with db.transaction() as c:
        for _ in range(10 if scopes else 1):                       # without a row policy: one page, exactly as before
            rows, tier = _page(c, tier, tokens, qn, allowed, off, size)
            hits = [{"doctype": r["ref_doctype"], "name": r["ref_name"], "title": r["title"] or r["ref_name"]} for r in rows]
            out += _within_scope(c, hits, scopes)
            if len(out) >= limit or len(rows) < size:
                break
            off += size
    return out[:limit]
