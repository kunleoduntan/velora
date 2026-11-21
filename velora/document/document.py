"""The Document engine: lifecycle, validation, persistence.

Lifecycle order (v1 - this is the contract):

  insert : permission(create) -> defaults/coercion -> before_insert -> naming
           -> before_validate -> validate -> before_save -> field checks
           -> DB write -> after_insert -> on_update -> after_save
  save   : permission(write) -> lock row + optimistic-lock check -> coercion
           -> before_validate -> validate -> before_save -> field checks
           -> DB write -> on_update -> after_save
  submit : permission(submit) -> lock -> docstatus=1 -> before_validate -> validate
           -> before_submit -> field checks -> DB write -> on_update -> on_submit -> after_save
  cancel : permission(cancel) -> lock -> docstatus=2 -> before_cancel -> DB write
           -> on_update -> on_cancel -> after_save
  delete : permission(delete) -> before_delete -> link-integrity check -> DB delete -> after_delete

Everything runs in ONE database transaction; any exception rolls it all back.
Each event runs the controller method first, then handlers registered by apps
through `doc_events` in their hooks.py.
"""
from __future__ import annotations

import functools

import secrets
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

import re
from sqlalchemy import String, and_, cast, delete as sa_delete, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from .. import db, naming, site as site_mod
from ..db.system import version as version_table
from ..db.tables import get_table
from ..exceptions import (DocStatusError, DoesNotExistError, DuplicateEntryError, LinkValidationError,
                          MandatoryError, TimestampMismatchError, ValidationError)
from ..meta.registry import registry
from ..meta.conditions import evaluate_condition
from ..permissions import check_permission, check_document_permission, has_document_permission, has_permission, shared_names, get_session, check_field_write, filter_dict, field_access, row_policy_sql, check_row_policy


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, microsecond precision


def _empty(v) -> bool:
    return v is None or v == "" or v == []


def _restoring(fn):
    """A save/submit/cancel that FAILS must leave the in-memory document exactly as it was (timestamp, status, name, child rows),
    so the caller can fix the problem and simply retry. The database side is already rolled back by the transaction."""
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        tables = {f.fieldname: list(getattr(self, f.fieldname) or []) for f in self.meta.table_fields}
        snap = (dict(self.__dict__), tables, {id(r): dict(r.__dict__) for rows in tables.values() for r in rows})
        try:
            return fn(self, *a, **kw)
        except BaseException:
            state, tbls, rowstate = snap
            self.__dict__.clear()
            self.__dict__.update(state)
            for fname, rows in tbls.items():
                getattr(self, fname)[:] = rows
                for r in rows:
                    r.__dict__.clear()
                    r.__dict__.update(rowstate[id(r)])
            raise
    return wrapper


def _why_link_refused(f, value) -> str:
    """Say in plain words which condition of a Link field the chosen record fails, and what to do about it."""
    rule = " and ".join(f"{x[0].replace('_', ' ')} {x[1]} {x[2]}" for x in f.link_filters)
    try:
        fields = list(dict.fromkeys(str(x[0]) for x in f.link_filters))
        rec = (get_list(f.options, filters=[["name", "=", value]], fields=fields, limit=1, ignore_permissions=True) or [{}])[0]
    except Exception:  # noqa: BLE001 - the explanation is a courtesy; the refusal stands
        return f"It must have {rule}."
    notes = []
    for x in f.link_filters:
        name, op, want = x[0], x[1], x[2]
        if name not in rec or str(op) != "=":
            continue
        if str(rec[name]) == str(want):
            continue
        if name == "is_group" and str(want) in ("0", "False"):
            notes.append("it is a group (heading) account, which only adds up the accounts under it. Choose a posting account, or one of its sub-accounts")
        elif name == "disabled" and str(want) in ("0", "False"):
            notes.append("it is disabled. Enable it or choose another")
        else:
            notes.append(f"its {name.replace('_', ' ')} is {rec[name]!r} but it must be {want!r}")
    return ("Because " + "; and ".join(notes) + ".") if notes else f"It must have {rule}."


class Document:
    def __init__(self, meta, values: dict | None = None):
        self.meta = meta
        self.doctype = meta.name
        self.flags = SimpleNamespace(ignore_permissions=False)
        self._is_new = True
        self._old: dict | None = None
        for c in meta.system_columns:
            setattr(self, c, None)
        self.docstatus = 0
        for f in meta.value_fields:
            setattr(self, f.fieldname, None)
        for f in meta.table_fields:
            setattr(self, f.fieldname, [])
        if values:
            self.update(values)

    # ---- dict-ish API --------------------------------------------------------
    def get(self, fieldname, default=None):
        return getattr(self, fieldname, default)

    def set(self, fieldname, value):
        self.update({fieldname: value})

    def update(self, values: dict):
        allowed = set(self.meta.system_columns) | {f.fieldname for f in self.meta.value_fields}
        for k, v in values.items():
            if k == "doctype":
                continue
            f = self.meta.get_field(k)
            if f is not None and f.is_table:
                setattr(self, k, [])
                for row in v or []:
                    self.append(k, row)
            elif k in allowed:
                setattr(self, k, v)
            else:
                raise ValidationError(f"{self.doctype}: unknown field {k!r}")
        return self

    def append(self, tablefield: str, row: dict | "Document" = None):
        f = self.meta.get_field(tablefield)
        if f is None or not f.is_table:
            raise ValidationError(f"{self.doctype}.{tablefield} is not a table field")
        child_meta = registry.get(f.options)
        if isinstance(row, Document):
            child = row
        else:
            child = registry.controller_for(child_meta.name)(child_meta, row or {})
        getattr(self, tablefield).append(child)
        return child

    def is_new(self) -> bool:
        return self._is_new

    def as_dict(self) -> dict:
        out = {"doctype": self.doctype}
        values = {c: getattr(self, c) for c in self.meta.column_names()}
        out.update(filter_dict(self.doctype, values))
        for f in self.meta.table_fields:
            if field_access(self.doctype, f.fieldname) != "hidden":
                out[f.fieldname] = [ch.as_dict() for ch in getattr(self, f.fieldname)]
        return out

    # ---- lifecycle hooks (override in controllers) --------------------------
    def before_insert(self): pass
    def after_insert(self): pass
    def before_validate(self): pass
    def validate(self): pass
    def before_save(self): pass
    def on_update(self): pass
    def after_save(self): pass
    def before_submit(self): pass
    def on_submit(self): pass
    def before_cancel(self): pass
    def on_cancel(self): pass
    def before_delete(self): pass
    def after_delete(self): pass

    def run_method(self, event: str):
        getattr(self, event)()
        for handler in registry.event_handlers(self.doctype, event):
            handler(self)
        # Company-local Server Scripts run after trusted installed-app hooks. They execute
        # in the framework's restricted AST-allowlisted Python subset and share the transaction.
        try:
            from ..scripts import run_server_scripts
            run_server_scripts(self, event)
        except ImportError:
            pass
        # Company-local automation rules enqueue only allow-listed installed-app handlers.
        try:
            from ..workflow_automation import dispatch_automations
            dispatch_automations(self, event)
        except ImportError:
            pass

    # ---- public persistence API ---------------------------------------------
    @_restoring
    def _record_activity(self, event_type: str, *, changed_fields=None, summary: str | None = None, metadata=None):
        """Persist a safe lifecycle event in the same transaction as this document operation."""
        from ..activity import record_event
        return record_event(
            event_type,
            f"{self.doctype} {self.name} {event_type}",
            doctype=self.doctype,
            document_name=self.name,
            changed_fields=changed_fields or [],
            summary=summary,
            metadata=metadata,
            source="system",
        )

    def _activity_changed_fields(self, new: bool = False):
        """Return changed field identifiers only; never copy document values into the audit stream."""
        changed = []
        for field in self.meta.value_fields:
            if field.fieldname in {"owner", "creation", "modified", "modified_by", "docstatus"}:
                continue
            current = self.get(field.fieldname)
            previous = None if new or not self._old else self._old.get(field.fieldname)
            if new and current is not None or not new and current != previous:
                changed.append(field.fieldname)
        for field in self.meta.table_fields:
            current = self.get(field.fieldname) or []
            previous = None if new or not self._old else self._old.get(field.fieldname)
            if new and current or not new and current != previous:
                changed.append(field.fieldname)
        return changed

    @_restoring
    def insert(self, ignore_permissions: bool = False):
        self.flags.ignore_permissions = self.flags.ignore_permissions or ignore_permissions
        self._check_perm("create")
        with db.transaction():
            self._stamp(new=True)
            self.docstatus = 0
            self._prepare()
            from .. import workflows as _wf
            _workflow = _wf.prepare_insert(self)                       # a new document starts where its approval workflow starts
            _wf.settle(self)                                           # ... or, with no workflow, is simply approved
            self.run_method("before_insert")
            if self.meta.is_submittable and self.get("amended_from"):
                from . import amend
                amend.check_amendment(self.doctype, self.get("amended_from"))          # only a cancelled document, only once
                if not self.name:
                    self.name = amend.amended_name(self.doctype, self.get("amended_from"))
                    if (self.meta.autoname or "").startswith("field:"):
                        self.set(self.meta.autoname[6:], self.name)                     # (the field that IS the name carries it)
            # trusted code may pre-set a name; otherwise the autoname rule decides
            self.name = str(self.name).strip() if self.name else self._new_name()
            self._link_children()
            self.run_method("before_validate")
            self.run_method("validate")
            self.run_method("before_save")
            self._check_fields()
            self._check_field_permissions(new=True)
            check_row_policy(self.doctype, "create", self._row_values())
            self._write(insert_=True)
            self._is_new = False
            _wf.after_insert(self, _workflow)
            self.run_method("after_insert")
            self.run_method("on_update")
            self.run_method("after_save")
            self._record_activity("created", changed_fields=self._activity_changed_fields(new=True),
                                  summary="Document created")
        return self

    @_restoring
    def save(self, ignore_permissions: bool = False):
        if self._is_new:
            return self.insert(ignore_permissions)
        self.flags.ignore_permissions = self.flags.ignore_permissions or ignore_permissions
        self._check_perm("write")
        with db.transaction():
            self._lock_and_check()
            check_row_policy(self.doctype, "write", self._old)
            if self._old["docstatus"] != 0:
                raise DocStatusError(f"{self.doctype} {self.name} is {'submitted' if self._old['docstatus'] == 1 else 'cancelled'} and cannot be edited")
            self._stamp(new=False)
            self.docstatus = 0
            from .. import workflows as _wf
            _wf.guard_state_change(self)
            _wf.settle(self)
            _wf.guard_locked(self)
            self._prepare()
            self._link_children()
            self.run_method("before_validate")
            self.run_method("validate")
            self.run_method("before_save")
            self._check_fields()
            self._check_field_permissions()
            check_row_policy(self.doctype, "write", self._row_values())
            self._write(insert_=False)
            self.run_method("on_update")
            self.run_method("after_save")
            self._track_changes()
            self._record_activity("updated", changed_fields=self._activity_changed_fields(),
                                  summary="Document updated")
        return self

    def submit(self, ignore_permissions: bool = False):
        self._transition("submit", ignore_permissions)
        return self

    def cancel(self, ignore_permissions: bool = False, reason: str | None = None):
        self._transition("cancel", ignore_permissions, reason=reason)
        return self

    def delete(self, ignore_permissions: bool = False, reason: str | None = None):
        self.flags.ignore_permissions = self.flags.ignore_permissions or ignore_permissions
        self._check_perm("delete")
        with db.transaction() as conn:
            self._lock_and_check()
            check_row_policy(self.doctype, "delete", self._old)
            if self._old["docstatus"] != 0:
                raise DocStatusError("Only draft documents may be deleted. Submitted or cancelled documents must remain in the permanent audit history.")
            self.run_method("before_delete")
            from .recycle_bin import archive_document
            archive_document(self, reason=reason)
            self._check_links_to_me()
            for f in self.meta.table_fields:
                ct = get_table(f.options)
                conn.execute(sa_delete(ct).where(ct.c.parent == self.name, ct.c.parenttype == self.doctype, ct.c.parentfield == f.fieldname))
            t = get_table(self.doctype)
            conn.execute(sa_delete(t).where(t.c.name == self.name))
            self.run_method("after_delete")
            self._record_activity("deleted", summary="Draft moved to Deleted Documents inbox", metadata={"recyclable": True, "reason": str(reason or "No reason supplied")[:500], "reason_missing": not bool(reason)})

    def reload(self):
        fresh = get_doc(self.doctype, self.name, ignore_permissions=True)
        self.__dict__.update({k: v for k, v in fresh.__dict__.items() if k != "flags"})
        return self

    # ---- internals ------------------------------------------------------------
    def _check_perm(self, ptype):
        if not self.flags.ignore_permissions:
            if self.name and ptype in ("read", "write"):
                check_document_permission(self.meta, ptype, self.name)
            else:
                check_permission(self.meta, ptype)

    def _check_field_permissions(self, new: bool = False):
        """Enforce server-side field policy for supplied/changed values, including child rows."""
        if self.flags.ignore_permissions or get_session().user == "Administrator":
            return
        changed = {}
        for f in self.meta.value_fields:
            value = getattr(self, f.fieldname)
            old = None if new or not self._old else self._old.get(f.fieldname)
            if new and value is not None or not new and value != old:
                if new and f.fieldname in getattr(self.flags, "workflow_fields", ()):
                    continue      # the approval workflow set this field, not the person
                if new and f.default is not None and str(value) == str(f.default):
                    continue      # a field's own starting value is not something the person wrote, so a read-only field may still start at its default
                changed[f.fieldname] = value
        check_field_write(self.doctype, changed)
        for table_field in self.meta.table_fields:
            for child in getattr(self, table_field.fieldname):
                child._check_field_permissions(new=child.is_new())

    def _stamp(self, new: bool):
        ts, user = now(), get_session().user
        if new:
            self.owner, self.creation = user, ts
        self.modified, self.modified_by = ts, user

    def _new_name(self):
        return naming.make_name(self.meta, self)

    @_restoring
    def _transition(self, action: str, ignore_permissions: bool, reason: str | None = None):
        if not self.meta.is_submittable:
            raise DocStatusError(f"{self.doctype} is not submittable")
        self.flags.ignore_permissions = self.flags.ignore_permissions or ignore_permissions
        self._check_perm(action)
        with db.transaction():
            self._lock_and_check()
            check_row_policy(self.doctype, action, self._old)
            current = self._old["docstatus"]
            if action == "submit":
                if current != 0:
                    raise DocStatusError("Only a draft can be submitted")
                from .. import workflows as _wf
                _wf.settle(self)
                _wf.guard_submit(self)
                self._stamp(new=False)
                self.docstatus = 1
                self._prepare()
                self._link_children()
                self.run_method("before_validate")
                self.run_method("validate")
                self.run_method("before_submit")
                self._check_fields()
                self._check_field_permissions()
                check_row_policy(self.doctype, "submit", self._row_values())
                self._write(insert_=False)
                self.run_method("on_update")
                self.run_method("on_submit")
                self._record_activity("submitted", changed_fields=["docstatus"],
                                      summary="Document submitted")
            else:
                if current != 1:
                    raise DocStatusError("Only a submitted document can be cancelled")
                # A posted financial/stock source must have a real, transactional cancellation handler.
                # The handler appends the exact reversal through the relevant central posting engine.
                if self.get("posting_batch") or self.get("inventory_posting_batch"):
                    custom_cancel = type(self).on_cancel is not Document.on_cancel
                    registered_cancel = bool(registry.event_handlers(self.doctype, "on_cancel"))
                    if not (custom_cancel or registered_cancel):
                        raise DocStatusError("This document has a financial or inventory posting batch but no verified on_cancel handler. Cancellation is blocked until its linked reversal handler is implemented.")
                if not getattr(self.flags, "ignore_links", False):
                    from .. import linked
                    linked.check_can_cancel(self)               # ERPNext's rule: no submitted document may still depend on this one
                self._stamp(new=False)
                self.docstatus = 2
                self.flags.cancellation_reason = str(reason or "No reason supplied")[:500]
                self.run_method("before_cancel")
                self._write(insert_=False)
                self.run_method("on_update")
                self.run_method("on_cancel")
                self._record_activity("cancelled", changed_fields=["docstatus"],
                                      summary="Document cancelled", metadata={"reason": self.flags.cancellation_reason, "reason_missing": not bool(reason)})
            self.run_method("after_save")

    def _lock_and_check(self):
        """Lock the row (SELECT ... FOR UPDATE) and detect concurrent edits."""
        t = get_table(self.doctype)
        row = db.conn().execute(select(t).where(t.c.name == self.name).with_for_update()).mappings().first()
        if row is None:
            raise DoesNotExistError(f"{self.doctype} {self.name} does not exist")
        self.modified = self._coerce_datetime(self.modified)   # may arrive as an ISO string from a client
        if self.modified is not None and row["modified"] != self.modified:
            raise TimestampMismatchError(f"{self.doctype} {self.name} was modified by someone else. Reload and retry.")
        self._old = dict(row)

    # ---- defaults, coercion -------------------------------------------------
    def _prepare(self):
        for f in self.meta.value_fields:
            v = getattr(self, f.fieldname)
            if _empty(v) and f.default is not None:
                v = now() if f.default == "Now" else (now().date() if f.default == "Today" else f.default)
            if f.fieldtype == "Check" and _empty(v):
                v = 0
            setattr(self, f.fieldname, self._coerce(f, v))
        for c in ("creation", "modified"):
            setattr(self, c, self._coerce_datetime(getattr(self, c)))
        self._apply_fetch()
        for f in self.meta.table_fields:
            for i, ch in enumerate(getattr(self, f.fieldname), start=1):
                ch.idx = i
                ch._prepare()

    def _apply_fetch(self):
        """ERPNext-style 'fetch from': copy a field of the linked document when this field is empty or its link changed.

        A field declared with ``fetch_from: "item_code.item_name"`` is filled from Item.item_name. It is only
        written while empty, or when the link itself was changed since the stored version, so a value the user
        typed over a fetched one is never silently replaced on a later save of the same link.
        """
        fetched = [f for f in self.meta.value_fields if f.fetch_from]
        if not fetched:
            return
        old = getattr(self, "_old", None) or {}
        for f in fetched:
            link_name, _, target = f.fetch_from.partition(".")
            link_field = self.meta.get_field(link_name)
            linked = getattr(self, link_name, None)
            if not link_field or _empty(linked):
                continue
            changed = bool(old) and old.get(link_name) != linked
            current = getattr(self, f.fieldname)
            blank = _empty(current) or (f.fieldtype == "Check" and not old and not current)      # a new document's unticked box has nothing of its own to protect
            if not (blank or changed):
                continue
            try:
                table = get_table(link_field.options)
                if target not in table.c:
                    continue
                row = db.conn().execute(select(table.c[target]).where(table.c.name == linked)).first()
            except Exception:  # noqa: BLE001 - a missing target never blocks saving; Link validation reports a bad link
                continue
            if row is not None and row[0] is not None:
                setattr(self, f.fieldname, self._coerce(f, row[0]))

    @staticmethod
    def _coerce_datetime(v):
        if isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if isinstance(v, datetime) and v.tzinfo:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v

    def _coerce(self, f, v):
        if v == "":
            v = None  # empty string == NULL everywhere (keeps Oracle/PostgreSQL behaviour identical)
        if v is None:
            return None
        try:
            t = f.fieldtype
            if t == "Int":
                return int(v)
            if t == "Float":
                return float(v)
            if t == "Currency":
                return Decimal(str(v))
            if t == "Check":
                return 0 if str(v).lower() in ("0", "false", "no", "") else 1
            if t == "Date":
                if isinstance(v, datetime):
                    return v.date()
                return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
            if t == "Datetime":
                return self._coerce_datetime(v if isinstance(v, (str, datetime)) else str(v))
            if t in ("Data", "Select", "Link", "Text"):
                v = str(v)
                if t == "Data" and len(v) > (f.length or 255):
                    raise ValidationError(f"{self.doctype}.{f.fieldname}: longer than {f.length or 255} characters")
                return v
        except (ValueError, InvalidOperation, TypeError):
            raise ValidationError(f"{self.doctype}.{f.fieldname}: {v!r} is not a valid {f.fieldtype}") from None
        return v

    def _link_children(self):
        for f in self.meta.table_fields:
            for i, ch in enumerate(getattr(self, f.fieldname), start=1):
                ch.parent, ch.parenttype, ch.parentfield, ch.idx = self.name, self.doctype, f.fieldname, i
                ch.owner, ch.creation = ch.owner or self.owner, ch.creation or self.creation
                ch.modified, ch.modified_by, ch.docstatus = self.modified, self.modified_by, self.docstatus
                if not ch.name:
                    ch.name = naming.make_name(ch.meta, ch)

    # ---- validation -------------------------------------------------------------
    def _check_fields(self, label: str = ""):
        seen_links: dict = {}
        where = label or self.doctype
        for f in self.meta.value_fields:
            v = getattr(self, f.fieldname)
            is_required = f.required or evaluate_condition(f.mandatory_depends_on, self)
            if is_required and _empty(v):
                raise MandatoryError(f"{where}: {f.label or f.fieldname} is required")
            if _empty(v):
                continue
            if f.fieldtype == "Select" and v not in f.choices:
                raise ValidationError(f"{where}: {f.label or f.fieldname} must be one of {f.choices}, got {v!r}")
            if f.fieldtype == "Link":
                key = (f.options, v)
                if key not in seen_links:
                    if f.options == "DocType":                           # doctypes live in the registry, not in a table
                        try:
                            registry.get(str(v)); seen_links[key] = True
                        except Exception:  # noqa: BLE001
                            seen_links[key] = False
                    else:
                        seen_links[key] = db.exists(f.options, v)
                if not seen_links[key]:
                    raise LinkValidationError(f"{where}: {f.options} {v!r} does not exist ({f.label or f.fieldname})")
                if f.link_filters:                                          # the field only accepts records that meet its conditions (e.g. posting accounts)
                    fkey = (f.options, v, str(f.link_filters))
                    if fkey not in seen_links:
                        seen_links[fkey] = bool(get_list(f.options, filters=[["name", "=", v]] + [list(x) for x in f.link_filters], fields=["name"], limit=1, ignore_permissions=True))
                    if not seen_links[fkey]:
                        raise LinkValidationError(f"{where}: {f.options} {v!r} is not allowed here. {_why_link_refused(f, v)}")
        for f in self.meta.table_fields:
            rows = getattr(self, f.fieldname)
            if (f.required or evaluate_condition(f.mandatory_depends_on, self)) and not rows:
                raise MandatoryError(f"{where}: {f.label or f.fieldname} needs at least one row")
            for ch in rows:
                ch._check_fields(f"{self.doctype} > {f.label or f.fieldname} row {ch.idx}")

    # ---- persistence ----------------------------------------------------------
    def _row_values(self) -> dict:
        return {c: getattr(self, c) for c in self.meta.column_names()}

    def _write(self, insert_: bool):
        conn, t = db.conn(), get_table(self.doctype)
        try:
            if insert_:
                conn.execute(insert(t).values(**self._row_values()))
            else:
                vals = self._row_values()
                vals.pop("name")
                conn.execute(update(t).where(t.c.name == self.name).values(**vals))
        except IntegrityError as e:
            if insert_ or "unique" in str(e.orig).lower():
                raise DuplicateEntryError(f"{self.doctype} {self.name!r} already exists or a unique field is duplicated") from e
            raise
        for f in self.meta.table_fields:
            self._write_children(f)

    def _write_children(self, f):
        conn, ct = db.conn(), get_table(f.options)
        rows = getattr(self, f.fieldname)
        existing = set(conn.execute(select(ct.c.name).where(
            ct.c.parent == self.name, ct.c.parenttype == self.doctype, ct.c.parentfield == f.fieldname)).scalars())
        keep = {ch.name for ch in rows}
        if existing - keep:
            conn.execute(sa_delete(ct).where(ct.c.name.in_(existing - keep)))
        for ch in rows:
            vals = ch._row_values()
            if ch.name in existing:
                vals.pop("name")
                conn.execute(update(ct).where(ct.c.name == ch.name).values(**vals))
            else:
                conn.execute(insert(ct).values(**vals))

    def _check_links_to_me(self):
        conn = db.conn()
        for dt, f in registry.links_to(self.doctype):
            t = get_table(dt.name)
            hit = conn.execute(select(t.c.name).where(t.c[f.fieldname] == self.name).limit(1)).first()
            if hit:
                raise LinkValidationError(f"Cannot delete {self.doctype} {self.name}: it is linked from {dt.name} {hit[0]}")

    def _track_changes(self):
        if not self.meta.track_changes or not self._old:
            return
        changed = {}
        for f in self.meta.value_fields:
            old, new = self._old.get(f.fieldname), getattr(self, f.fieldname)
            if old != new:
                changed[f.fieldname] = [_jsonable(old), _jsonable(new)]
        if changed:
            db.conn().execute(insert(version_table).values(
                name=secrets.token_hex(8), ref_doctype=self.doctype, docname=self.name,
                data={"changed": changed}, owner=get_session().user, creation=now()))


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


# ---- module-level helpers ---------------------------------------------------------
def new_doc(doctype: str, **values) -> Document:
    meta = registry.get(doctype)
    return registry.controller_for(doctype)(meta, values)


def get_doc(doctype, name=None, ignore_permissions: bool = False) -> Document:
    """get_doc("Customer", "CUST-0001") loads; get_doc({"doctype": ..., ...}) builds a new unsaved doc."""
    if isinstance(doctype, dict):
        values = dict(doctype)
        return new_doc(values.pop("doctype"), **values)
    meta = registry.get(doctype)
    if not ignore_permissions and not has_permission(meta, "read") and not has_document_permission(meta, "read", name):
        # Do not reveal whether an unshared record exists to a user without DocType read access.
        from ..exceptions import PermissionDenied
        raise PermissionDenied(f"You do not have read permission on {doctype} {name}")
    with db.transaction() as conn:
        t = get_table(doctype)
        stmt = select(t).where(t.c.name == name)
        row_scope = row_policy_sql(doctype, "read", t) if not ignore_permissions else None
        if row_scope is not None: stmt = stmt.where(row_scope)
        row = conn.execute(stmt).mappings().first()
        if row is None:
            raise DoesNotExistError(f"{doctype} {name} does not exist")
        doc = registry.controller_for(doctype)(meta)
        for c in meta.column_names():
            setattr(doc, c, row[c])
        for f in meta.table_fields:
            ct, cmeta = get_table(f.options), registry.get(f.options)
            for r in conn.execute(select(ct).where(ct.c.parent == name, ct.c.parenttype == doctype,
                                                   ct.c.parentfield == f.fieldname).order_by(ct.c.idx)).mappings():
                child = registry.controller_for(cmeta.name)(cmeta)
                for c in cmeta.column_names():
                    setattr(child, c, r[c])
                child._is_new = False
                getattr(doc, f.fieldname).append(child)
    doc._is_new = False
    return doc


_OPS = {"=": "__eq__", "!=": "__ne__", ">": "__gt__", "<": "__lt__", ">=": "__ge__", "<=": "__le__"}


_TEXT_TYPES = {"Data", "Text", "Select", "Link"}
_SYSTEM_TYPES = {"name": "Data", "owner": "Data", "modified_by": "Data", "creation": "Datetime",
                 "modified": "Datetime", "docstatus": "Int", "idx": "Int", "parent": "Data", "parenttype": "Data", "parentfield": "Data"}


def _filter_type(meta, fld):
    f = meta.get_field(fld)
    return f.fieldtype if f else _SYSTEM_TYPES.get(fld, "Data")


def _coerce_filter(ftype, v, upper_bound=False):
    """Filter values arrive as JSON (strings); SQLite and PostgreSQL both need typed parameters."""
    if v is None:
        return None
    try:
        if ftype in ("Int", "Check"):
            return int(v)
        if ftype in ("Float", "Currency"):
            return Decimal(str(v)) if ftype == "Currency" else float(v)
        if ftype == "Date":
            return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10])
        if ftype == "Datetime":
            if isinstance(v, datetime):
                return v
            txt = str(v)
            dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            if len(txt) == 10 and upper_bound:      # "to 2026-11-07" means through the end of that day
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return dt
    except (ValueError, InvalidOperation, TypeError):
        raise ValidationError(f"{v!r} is not a valid {ftype} filter value") from None
    return str(v)


_SEARCH_TYPES = {"Data", "Small Text", "Text", "Link", "Select", "Email", "Phone", "Code", "Dynamic Link", "Long Text"}
_SEARCH_CAST_TYPES = {"Int", "Float", "Currency", "Percent", "Date", "Datetime"}     # found too (an invoice number, a date typed as 2026-11), compared as text
_SEARCH_SENSITIVE = re.compile(r"pass(word)?|secret|token|api_?key|private_?key|otp|pin$", re.I)
SEARCH_COLUMNS = 14


def search_columns(doctype, meta, t):
    """The columns a search box looks in: ID, title, then the readable text columns (list-view ones first), bounded."""
    names = ["name"]
    if meta.title_field and meta.title_field != "name":
        names.append(meta.title_field)
    rest = [f for f in meta.value_fields if f.fieldtype in (_SEARCH_TYPES | _SEARCH_CAST_TYPES) and not f.hidden and f.fieldname not in names and not _SEARCH_SENSITIVE.search(f.fieldname)]
    rest.sort(key=lambda f: (f.fieldtype in _SEARCH_CAST_TYPES, not f.in_list_view, not f.in_standard_filter, not f.required, f.fieldname))
    names += [f.fieldname for f in rest]
    casts = {f.fieldname for f in rest if f.fieldtype in _SEARCH_CAST_TYPES}
    return [(cast(t.c[n], String) if n in casts else t.c[n]) for n in names if n in t.c and (n == "name" or field_access(doctype, n) != "hidden")][:SEARCH_COLUMNS]


def _search_condition(doctype, t, meta, text):
    """Every word must appear somewhere (case-insensitive), so 'rent expense' finds the account named Rent - Expense."""
    text = str(text or "").strip()
    if len(text) > 1 and text.startswith("%") and text.endswith("%"):
        text = text[1:-1]                                                   # the list filter bar wraps a typed word in %...%: that is wildcard syntax, not part of the word
    words = [w for w in re.split(r"\s+", text.strip()) if w][:6]
    if not words:
        return None
    cols = search_columns(doctype, meta, t)
    def esc(w): return w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return and_(*[or_(*[c.ilike(f"%{esc(w)}%", escape="\\") for c in cols]) for w in words])


def _conditions(doctype, t, cols, filters, meta=None):
    meta = meta or registry.get(doctype)
    if isinstance(filters, dict):
        filters = [[k, "=", v] for k, v in filters.items()]
    out = []
    for flt in filters or []:
        if len(flt) != 3:
            raise ValidationError(f"Filter must be [field, operator, value], got {flt!r}")
        fld, op, val = flt
        if fld == "_search":                                   # one box over name, title and every readable text column
            cond = _search_condition(doctype, t, meta, val)
            if cond is not None:
                out.append(cond)
            continue
        if fld not in cols:
            raise ValidationError(f"{doctype}: cannot filter on unknown field {fld!r}")
        if field_access(doctype, fld) == "hidden":
            from ..exceptions import PermissionDenied
            raise PermissionDenied(f"Field {doctype}.{fld} is hidden and cannot be filtered")
        col, ft, op = t.c[fld], _filter_type(meta, fld), str(op).lower()
        if op in _OPS:
            out.append(getattr(col, _OPS[op])(_coerce_filter(ft, val)))
        elif op in ("like", "not like"):
            if ft not in _TEXT_TYPES:
                raise ValidationError(f"Operator {op!r} only applies to text fields, not {ft}")
            out.append(col.ilike(str(val)) if op == "like" else col.not_ilike(str(val)))   # case-insensitive on EVERY database (PostgreSQL LIKE is not)
        elif op in ("in", "not in"):
            if not isinstance(val, (list, tuple)):
                raise ValidationError(f"Operator {op!r} needs a list of values")
            vals = [_coerce_filter(ft, v) for v in val]
            out.append(col.in_(vals) if op == "in" else col.not_in(vals))
        elif op == "between":
            if not isinstance(val, (list, tuple)) or len(val) != 2:
                raise ValidationError("Operator 'between' needs [from, to]")
            out.append(col.between(_coerce_filter(ft, val[0]), _coerce_filter(ft, val[1], upper_bound=True)))
        elif op in ("json_contains", "json_has_key"):
            if ft != "JSON":
                raise ValidationError(f"Operator {op!r} only applies to JSON fields, not {ft}")
            dialect = site_mod.current().engine.dialect.name
            if dialect != "postgresql":
                raise ValidationError(f"Operator {op!r} needs PostgreSQL (this database is {dialect})")
            from sqlalchemy import cast, literal
            from sqlalchemy.dialects.postgresql import JSONB
            doc = cast(col, JSONB)
            if op == "json_has_key":
                if not isinstance(val, str):
                    raise ValidationError("Operator 'json_has_key' needs a key name")
                out.append(doc.op("?")(val))
            else:
                import json as _json
                out.append(doc.op("@>")(cast(literal(_json.dumps(val)), JSONB)))      # "contains this structure": {"event": "New"} matches any document with that key and value
        elif op == "is":
            v = str(val).lower().replace(" ", "")
            if v not in ("set", "notset"):
                raise ValidationError("Operator 'is' needs 'set' or 'not set'")
            out.append(col.is_not(None) if v == "set" else col.is_(None))
        else:
            raise ValidationError(f"Unsupported filter operator {op!r}")
    return out


def get_count(doctype: str, filters=None, ignore_permissions: bool = False) -> int:
    from sqlalchemy import func
    meta = registry.get(doctype)
    shared_only = []
    if not ignore_permissions and not has_permission(meta, "read"):
        shared_only = shared_names(doctype, "read") + shared_names(doctype, "write")
        shared_only = list(dict.fromkeys(shared_only))
        if not shared_only:
            check_permission(meta, "read")
    t = get_table(doctype)
    stmt = select(func.count()).select_from(t)
    if shared_only:
        stmt = stmt.where(t.c.name.in_(shared_only))
    row_scope = row_policy_sql(doctype, "read", t) if not ignore_permissions else None
    if row_scope is not None: stmt = stmt.where(row_scope)
    for cond in _conditions(doctype, t, set(meta.column_names()), filters, meta):
        stmt = stmt.where(cond)
    with db.transaction() as conn:
        return conn.execute(stmt).scalar_one()


def get_list(doctype: str, filters=None, fields=None, order_by: str | None = None,
             limit: int = 20, offset: int = 0, ignore_permissions: bool = False) -> list[dict]:
    """Safe generic query. Every field/operator is whitelisted; values are bound parameters."""
    meta = registry.get(doctype)
    shared_only = []
    if not ignore_permissions and not has_permission(meta, "read"):
        shared_only = list(dict.fromkeys(shared_names(doctype, "read") + shared_names(doctype, "write")))
        if not shared_only:
            check_permission(meta, "read")
    t = get_table(doctype)
    cols = set(meta.column_names())
    if fields is None:
        fields = ["name"] + [f.fieldname for f in meta.value_fields if f.in_list_view and field_access(doctype, f.fieldname) != "hidden"] + ["modified"]
    bad = [c for c in fields if c not in cols]
    hidden = [c for c in fields if c in cols and field_access(doctype, c) == "hidden"]
    if hidden:
        from ..exceptions import PermissionDenied
        raise PermissionDenied(f"Fields are not readable on {doctype}: {hidden}")
    if bad:
        raise ValidationError(f"{doctype}: unknown field(s) {bad}")
    stmt = select(*[t.c[c] for c in dict.fromkeys(fields)])
    if shared_only:
        stmt = stmt.where(t.c.name.in_(shared_only))
    row_scope = row_policy_sql(doctype, "read", t) if not ignore_permissions else None
    if row_scope is not None: stmt = stmt.where(row_scope)

    for cond in _conditions(doctype, t, cols, filters, meta):
        stmt = stmt.where(cond)

    ob = order_by or f"{meta.sort_field} {meta.sort_order}"
    fld, _, direction = ob.partition(" ")
    if fld not in cols or (direction or "asc").lower() not in ("asc", "desc"):
        raise ValidationError(f"Invalid order_by {ob!r}")
    stmt = stmt.order_by(t.c[fld].desc() if direction.lower() == "desc" else t.c[fld].asc(), t.c.name)
    stmt = stmt.limit(max(1, min(int(limit), 1000))).offset(max(0, int(offset)))
    with db.transaction() as conn:
        return [dict(r) for r in conn.execute(stmt).mappings()]


def get_group_by(doctype: str, field: str, filters=None, limit: int = 20) -> list[dict]:
    """Counts per value of a Select/Link/Check field (or owner/docstatus) - powers the list sidebar."""
    from sqlalchemy import func
    meta = registry.get(doctype)
    check_permission(meta, "read")
    if field_access(doctype, field) == "hidden":
        from ..exceptions import PermissionDenied
        raise PermissionDenied(f"Field {doctype}.{field} is hidden")
    f = meta.get_field(field)
    if not ((f and f.fieldtype in ("Select", "Link", "Check")) or field in ("owner", "docstatus")):
        raise ValidationError(f"Cannot group {doctype} by {field!r}")
    t = get_table(doctype)
    n = func.count().label("count")
    stmt = select(t.c[field].label("value"), n).group_by(t.c[field])
    row_scope = row_policy_sql(doctype, "read", t)
    if row_scope is not None: stmt = stmt.where(row_scope)
    for cond in _conditions(doctype, t, set(meta.column_names()), filters, meta):
        stmt = stmt.where(cond)
    stmt = stmt.order_by(n.desc(), t.c[field]).limit(max(1, min(int(limit), 100)))
    with db.transaction() as conn:
        return [dict(r) for r in conn.execute(stmt).mappings()]


def get_aggregate(doctype: str, fields: list[str], filters=None) -> dict:
    """SUM of numeric columns over ALL rows matching `filters` (not just a page) - powers the list's total row."""
    from sqlalchemy import func
    meta = registry.get(doctype)
    check_permission(meta, "read")
    hidden = [f for f in fields if field_access(doctype, f) == "hidden"]
    if hidden:
        from ..exceptions import PermissionDenied
        raise PermissionDenied(f"Fields are hidden on {doctype}: {hidden}")
    bad = [f for f in fields if not ((fl := meta.get_field(f)) and fl.fieldtype in ("Int", "Float", "Currency"))]
    if bad or not fields:
        raise ValidationError(f"{doctype}: can only total numeric fields; not allowed: {bad or 'nothing given'}")
    t = get_table(doctype)
    stmt = select(*[func.sum(t.c[f]).label(f) for f in dict.fromkeys(fields)])
    row_scope = row_policy_sql(doctype, "read", t)
    if row_scope is not None: stmt = stmt.where(row_scope)
    for cond in _conditions(doctype, t, set(meta.column_names()), filters, meta):
        stmt = stmt.where(cond)
    with db.transaction() as conn:
        row = conn.execute(stmt).mappings().one()
    return {k: (None if v is None else float(v)) for k, v in row.items()}
