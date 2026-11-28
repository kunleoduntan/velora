"""The Database screen of the Server Console: browse tables, run SQL, and remove stubborn data, safely.

Every rule is enforced here, on the server:

* Platform administrators only, and anything that changes data also needs the unlocked console (see elevation.py).
* Reading runs inside a read-only transaction with a time limit, so even a clever SELECT (a data-changing WITH, a function with side effects) cannot write.
* A changing statement is first run as a preview: it is executed and rolled back, and you are shown how many rows it would touch. Only the exact statement that
  was previewed can then be committed (a signed plan token ties the two together), and a backup of the company is taken just before it is applied.
* One statement at a time. Statements that reach outside the company's own database (attach/copy/extensions/roles/files/server settings) are refused outright.
* Every statement, read or write, is written to the audit log with who ran it and what it did.
"""
from __future__ import annotations

import datetime as dt
import decimal
import hashlib
import hmac
import re
import time

from sqlalchemy import inspect, text

from . import db
from .exceptions import PermissionDenied, ValidationError

READ_LIMIT = 500
TIMEOUT_SECONDS = 15
PLAN_TTL = 300
READ_WORDS = {"select", "with", "values", "explain", "show"}
WRITE_WORDS = {"insert", "update", "delete", "replace", "create", "alter", "drop", "truncate", "reindex"}
DDL_WORDS = {"create", "alter", "drop", "truncate", "reindex"}
FORBIDDEN = re.compile(
    r"\b(load_extension|pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|lo_import|lo_export|lo_unlink|lo_from_bytea|dblink\w*|pg_terminate_backend|"
    r"pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|set_config|pg_sleep_for|pg_shadow|pg_authid|pg_user_mapping|pg_file_settings|readfile|writefile|edit)\b|"
    r"\binto\s+(outfile|dumpfile)\b|"
    r"\b(create|alter|drop)\s+(or\s+replace\s+)?(unique\s+)?(role|user|database|extension|system|tablespace|server|function|procedure|language|trigger|"
    r"publication|subscription|schema|event|policy|rule|operator|group)\b|\b(grant|revoke)\b", re.I)
SAFE_PRAGMA = re.compile(r"^pragma\s+(table_info|table_xinfo|index_list|index_info|foreign_key_list|table_list)\s*\(\s*['\"]?[A-Za-z0-9_]+['\"]?\s*\)\s*;?$", re.I)


# ---- reading a statement without being fooled by quotes and comments ---------------------------------------------------------------------
def skeleton(sql: str) -> str:
    """The statement with comments, string literals and quoted names blanked out, so keywords can be looked for honestly."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j < 0:
                raise ValidationError("A comment is not closed")
            i = j + 2
            out.append(" ")
        elif c == "'":
            j = i + 1
            while True:
                j = sql.find("'", j)
                if j < 0:
                    raise ValidationError("A quote is not closed")
                if sql.startswith("''", j):
                    j += 2
                    continue
                break
            out.append("''")
            i = j + 1
        elif c == '"' or c == "`":
            j = sql.find(c, i + 1)
            if j < 0:
                raise ValidationError("A quote is not closed")
            out.append('"q"')
            i = j + 1
        elif c == "$":
            m = re.match(r"\$[A-Za-z_]*\$", sql[i:])
            if m:
                j = sql.find(m.group(0), i + len(m.group(0)))
                if j < 0:
                    raise ValidationError("A $$ quote is not closed")
                out.append("''")
                i = j + len(m.group(0))
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def classify(sql: str) -> tuple[str, str]:
    """('read' | 'write', first keyword). Refuses more than one statement and anything that reaches outside the company's database."""
    sql = str(sql or "").strip()
    if not sql:
        raise ValidationError("Type a statement")
    if len(sql) > 20000:
        raise ValidationError("The statement is too long (20,000 characters at most)")
    sk = skeleton(sql).strip()
    body = sk.rstrip(";").strip()
    if ";" in body:
        raise ValidationError("Run one statement at a time")
    first = (re.match(r"[A-Za-z]+", body) or [""])[0].lower() if body else ""
    if first == "pragma":
        if not SAFE_PRAGMA.match(body):
            raise PermissionDenied("Only table_info, index_list and similar read-only PRAGMAs are allowed")
        return "read", first
    if first not in READ_WORDS | WRITE_WORDS:
        raise ValidationError("Start with SELECT, WITH, INSERT, UPDATE, DELETE, CREATE, ALTER or DROP")
    bad = FORBIDDEN.search(body)
    if bad:
        raise PermissionDenied(f"'{bad.group(0).strip().lower()}' is not allowed here: it reaches outside this company's data")
    if first in READ_WORDS:
        return "read", first
    return "write", first


def _jsonable(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(v))} bytes>"
    return str(v)


def _ident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]{1,63}", str(name or "")):
        raise ValidationError("Invalid table or column name")
    return name


class DbConsole:
    """Works on the database of the company currently in scope (the caller wraps it in plane.company_scope)."""

    def __init__(self, sign_key: bytes, actor: str, company_id: str):
        self.key, self.actor, self.company = sign_key, actor, company_id

    # ---- tables ------------------------------------------------------------------------------------------------------------------------
    def tables(self) -> list[dict]:
        engine = db.get_engine()
        insp = inspect(engine)
        out = []
        with engine.connect() as conn:
            for t in sorted(insp.get_table_names()):
                try:
                    count = conn.execute(text(f'SELECT COUNT(*) FROM "{_ident(t)}"')).scalar()
                except Exception:  # noqa: BLE001
                    count = None
                out.append({"name": t, "rows": count, "columns": len(insp.get_columns(t))})
        return out

    def describe(self, table: str) -> dict:
        engine = db.get_engine()
        insp = inspect(engine)
        if table not in insp.get_table_names():
            raise ValidationError("No such table")
        pk = insp.get_pk_constraint(table).get("constrained_columns") or []
        return {"name": table, "primary_key": pk,
                "columns": [{"name": c["name"], "type": str(c["type"]), "nullable": bool(c.get("nullable", True))} for c in insp.get_columns(table)],
                "indexes": [{"name": i.get("name"), "columns": i.get("column_names"), "unique": bool(i.get("unique"))} for i in insp.get_indexes(table)]}

    def rows(self, table: str, limit: int = 50, offset: int = 0, column: str | None = None, value: str | None = None, order_by: str | None = None) -> dict:
        info = self.describe(table)
        names = [c["name"] for c in info["columns"]]
        limit, offset = max(1, min(int(limit), READ_LIMIT)), max(0, int(offset))
        where, params = "", {}
        if column:
            if column not in names:
                raise ValidationError("No such column")
            where, params = f'WHERE CAST("{column}" AS TEXT) LIKE :v', {"v": f"%{value or ''}%"}
        order = ""
        if order_by:
            col, _, direction = order_by.partition(" ")
            if col not in names:
                raise ValidationError("No such column")
            order = f'ORDER BY "{col}" {"DESC" if direction.lower() == "desc" else "ASC"}'
        elif info["primary_key"]:
            order = "ORDER BY " + ", ".join(f'"{c}"' for c in info["primary_key"])
        sql = f'SELECT * FROM "{table}" {where} {order} LIMIT {limit} OFFSET {offset}'
        result = self._read(sql, params)
        total = self._read(f'SELECT COUNT(*) FROM "{table}" {where}', params)["rows"][0][0]
        return {**result, "total": total, "primary_key": info["primary_key"], "table": table}

    # ---- reading -----------------------------------------------------------------------------------------------------------------------
    def _read(self, sql: str, params: dict | None = None) -> dict:
        engine = db.get_engine()
        started = time.time()
        if engine.dialect.name == "sqlite":
            raw = engine.raw_connection()
            try:
                cur = raw.cursor()
                cur.execute("PRAGMA query_only = ON")
                deadline = started + TIMEOUT_SECONDS
                raw.driver_connection.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)
                try:
                    cur.execute(sql, params or {})
                    cols = [d[0] for d in (cur.description or [])]
                    fetched = cur.fetchmany(READ_LIMIT + 1)
                except Exception as e:  # noqa: BLE001
                    raise ValidationError(self._clean_error(e)) from None
                finally:
                    raw.driver_connection.set_progress_handler(None, 0)
                    cur.execute("PRAGMA query_only = OFF")
            finally:
                raw.close()
        else:
            with engine.connect() as conn:
                try:
                    conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                    conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_SECONDS * 1000}")
                    res = conn.execute(text(sql), params or {})
                    cols = list(res.keys())
                    fetched = res.fetchmany(READ_LIMIT + 1)
                except Exception as e:  # noqa: BLE001
                    raise ValidationError(self._clean_error(e)) from None
                finally:
                    conn.rollback()
        truncated = len(fetched) > READ_LIMIT
        rows = [[_jsonable(v) for v in r] for r in fetched[:READ_LIMIT]]
        return {"columns": cols, "rows": rows, "truncated": truncated, "seconds": round(time.time() - started, 3)}

    @staticmethod
    def _clean_error(e: Exception) -> str:
        msg = str(getattr(e, "orig", None) or e).strip().splitlines()[0]
        return msg[:300]

    # ---- the one entry point for statements --------------------------------------------------------------------------------------------
    def _plan(self, sql: str, expires: int) -> str:
        digest = hashlib.sha256(sql.encode()).hexdigest()
        sig = hmac.new(self.key, f"{self.actor}:{self.company}:{digest}:{expires}".encode(), hashlib.sha256).hexdigest()
        return f"{expires}.{sig}"

    def _check_plan(self, sql: str, token: str | None):
        try:
            exp_s, _ = str(token or "").split(".", 1)
            exp = int(exp_s)
        except ValueError:
            raise ValidationError("Preview this statement first, then apply it") from None
        if exp < time.time():
            raise ValidationError("The preview is too old. Preview the statement again.")
        if not hmac.compare_digest(self._plan(sql, exp), str(token)):
            raise ValidationError("This is not the statement you previewed. Preview it again.")

    def run(self, sql: str, mode: str, *, elevated: bool, plan: str | None = None, backup=None, audit=None) -> dict:
        """mode: 'read' | 'preview' | 'apply'. `backup()` is called just before a change is applied; `audit(event, detail)` records every call."""
        kind, first = classify(sql)
        sql = sql.strip().rstrip(";").strip()
        short = sql[:2000]
        if mode == "read":
            if kind != "read":
                raise ValidationError("This statement changes data. Use Preview, then Apply (the console must be unlocked).")
            out = self._read(sql)
            audit and audit("db.read", {"company": self.company, "sql": short, "rows": len(out["rows"])})
            return {"kind": "read", **out}
        if kind != "write":
            raise ValidationError("Use Run for statements that only read")
        if not elevated:
            raise PermissionDenied("Unlock the Server Console first: changing data needs your password again.")
        engine = db.get_engine()
        ddl = first in DDL_WORDS
        if mode == "preview":
            if ddl and engine.dialect.name == "sqlite":
                affected = None                                             # SQLite cannot undo a schema change, so it is not run as a preview
            else:
                affected = self._execute(sql, rollback=True)
            expires = int(time.time()) + PLAN_TTL
            audit and audit("db.preview", {"company": self.company, "sql": short, "would_affect": affected})
            return {"kind": "preview", "would_affect": affected, "statement_kind": first.upper(), "plan": self._plan(sql, expires), "expires_in": PLAN_TTL,
                    "note": ("The effect of a schema change cannot be previewed on SQLite." if affected is None else None)}
        if mode == "apply":
            self._check_plan(sql, plan)
            if backup is not None:
                backup()
            affected = self._execute(sql, rollback=False)
            audit and audit("db.apply", {"company": self.company, "sql": short, "affected": affected})
            return {"kind": "applied", "affected": affected, "statement_kind": first.upper()}
        raise ValidationError("Unknown mode")

    def _execute(self, sql: str, *, rollback: bool) -> int | None:
        class _Undo(Exception):
            pass
        try:
            with db.transaction() as conn:
                if conn.dialect.name != "sqlite":
                    conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_SECONDS * 1000}")
                res = conn.execute(text(sql))
                n = res.rowcount if res.rowcount is not None and res.rowcount >= 0 else None
                if rollback:
                    raise _Undo()
                return n
        except _Undo:
            return n
        except Exception as e:  # noqa: BLE001
            raise ValidationError(self._clean_error(e)) from None


# ---- stuck documents: cancel, reopen or remove one document with everything that hangs off it -----------------------------------------------
ACTIONS = {"cancel": "mark as cancelled (docstatus 2)", "draft": "reopen as a draft (docstatus 0)", "delete": "delete the document and its table rows"}


def _children(doctype: str) -> list[tuple[str, str]]:
    """(child table name, child doctype) for every table field, one level at a time, depth-first."""
    from .db.tables import table_name
    from .site import current
    out = []
    meta = current().registry.get(doctype)
    for f in meta.fields:
        if f.fieldtype == "Table" and f.options:
            out.append((table_name(f.options), f.options))
            out += _children(f.options)
    return out


def force_document(console: DbConsole, doctype: str, name: str, action: str, mode: str, *, elevated: bool, confirm: str = "", plan: str | None = None,
                   backup=None, audit=None) -> dict:
    """Repair one stuck document. `mode` 'preview' counts the rows involved; 'apply' needs the matching plan and the document's name typed again."""
    from .db.tables import table_name
    if action not in ACTIONS:
        raise ValidationError("Unknown action")
    if not elevated:
        raise PermissionDenied("Unlock the Server Console first: this needs your password again.")
    from .site import current
    try:
        current().registry.get(doctype)
    except Exception:  # noqa: BLE001
        raise ValidationError("No such document type") from None
    table = table_name(doctype)
    with db.get_engine().connect() as conn:
        found = conn.execute(text(f'SELECT docstatus FROM "{table}" WHERE name = :n'), {"n": name}).first()
        if found is None:
            raise ValidationError(f"{doctype} {name} was not found")
        kids = _children(doctype)
        counts = {t: conn.execute(text(f'SELECT COUNT(*) FROM "{t}" WHERE parent = :n'), {"n": name}).scalar() for t, _ in kids}
    signature = f"FORCE:{action}:{doctype}:{name}"
    if mode == "preview":
        expires = int(time.time()) + PLAN_TTL
        audit and audit("db.force_preview", {"company": console.company, "doctype": doctype, "name": name, "action": action})
        return {"kind": "preview", "action": ACTIONS[action], "docstatus_now": found[0], "child_rows": {k: v for k, v in counts.items() if v},
                "plan": console._plan(signature, expires), "expires_in": PLAN_TTL,
                "warning": "Postings and links that other documents made from this one are NOT reversed or removed. Use this to clear a stuck record, not to correct accounts."}
    if mode != "apply":
        raise ValidationError("Unknown mode")
    console._check_plan(signature, plan)
    if confirm != name:
        raise ValidationError("Type the document's name exactly to confirm")
    if backup is not None:
        backup()
    with db.transaction() as conn:
        if action == "delete":
            for t, _ in kids:
                conn.execute(text(f'DELETE FROM "{t}" WHERE parent = :n'), {"n": name})
            conn.execute(text(f'DELETE FROM "{table}" WHERE name = :n'), {"n": name})
        else:
            conn.execute(text(f'UPDATE "{table}" SET docstatus = :d WHERE name = :n'), {"d": 2 if action == "cancel" else 0, "n": name})
    audit and audit("db.force_apply", {"company": console.company, "doctype": doctype, "name": name, "action": action, "child_rows": sum(counts.values())})
    return {"kind": "applied", "action": ACTIONS[action]}
