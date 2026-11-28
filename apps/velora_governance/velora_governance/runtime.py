"""The one place Velora Governance meets the host framework.

Governance code was written against a small document-API vocabulary (get_list, get_doc, has_permission, throw, whitelist, session, utils...).
`host` answers that vocabulary with Velora's own functions, so nothing is re-implemented here: every call lands in the framework's permission,
audit, naming and persistence code. Governance "single" settings records are ordinary documents with one fixed name.
"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import velora
from velora import get_count as _get_count, get_doc as _get_doc, get_list as _get_list, new_doc
from velora.exceptions import DoesNotExistError, PermissionDenied, ValidationError
from velora.meta.registry import registry
from velora.permissions import get_session, has_permission as _has_permission

SINGLE_NAME = "default"
_ALL_ROWS = 20000                      # "no limit" is bounded: governance lists page through the framework's 1000-row window


class _Utils:
    @staticmethod
    def today() -> str: return datetime.now().date().isoformat()

    @staticmethod
    def now_datetime() -> datetime: return datetime.now()


class _Session:
    @property
    def user(self) -> str: return get_session().user


class _Db:
    @staticmethod
    def commit() -> None:
        """The framework commits at the end of each request; nothing to do (kept so orchestration code reads the same everywhere)."""


_NL_FIELDS = {"for_user": "user", "email_content": "message", "document_type": "ref_doctype", "document_name": "ref_name"}


def _notification_log_values(values: dict) -> dict:
    """Governance describes a notification as (for_user, email_content, type, document_*); Velora Notify's Notification Log stores
    (user, message, priority, ref_*) with a delivery key that makes a repeat of the same reminder a no-op. Translated once, here."""
    out = {}
    for k, v in values.items():
        if k == "doctype": continue
        if k == "type": out["priority"] = "High" if v == "Alert" else "Normal"
        else: out[_NL_FIELDS.get(k, k)] = v
    subject = str(out.get("subject") or "")
    marker = subject.rsplit("[GAE-", 1)
    if len(marker) == 2 and subject.endswith("]"): out.setdefault("delivery_key", "gov-" + marker[1][:-1])
    out["subject"] = subject[:140]
    return out


class _NotificationLog:
    """A Notification Log being built attribute by attribute with governance's names."""
    def __init__(self, values=None):
        object.__setattr__(self, "_v", dict(values or {}))
        object.__setattr__(self, "name", None)
    def __setattr__(self, k, v): self._v[k] = v
    def __getattr__(self, k):
        try: return self._v[k]
        except KeyError: raise AttributeError(k)
    def insert(self, ignore_permissions=False, **_kw):
        doc = new_doc("Notification Log", **_notification_log_values(self._v)); doc.insert(ignore_permissions=ignore_permissions)
        object.__setattr__(self, "name", doc.name)
        return self


def _directory():
    c = velora.current_company()
    return getattr(c, "directory", None) if c else None


def _user_known(name: str) -> bool:
    d = _directory()
    return d.is_user(name) if d is not None else ("@" in str(name or ""))        # no company directory (library/single-site mode): an e-mail address is accepted


class Host:
    PermissionError = PermissionDenied
    ValidationError = ValidationError
    DoesNotExistError = DoesNotExistError
    utils = _Utils()
    session = _Session()
    db = _Db()

    def __init__(self):
        self.whitelisted: dict[str, object] = {}

    # ---- calling surface ----------------------------------------------------------------------------------------
    def whitelist(self, **_kw):
        def mark(fn):
            self.whitelisted[fn.__name__] = fn
            return fn
        return mark

    @staticmethod
    def throw(message, exc=None):
        raise (exc or ValidationError)(str(message))

    @staticmethod
    def as_json(value, **_kw) -> str:
        return json.dumps(value, default=str, indent=1)

    @staticmethod
    def has_permission(doctype, ptype="read", doc=None) -> bool:
        return bool(_has_permission(registry.get(doctype), ptype))

    # ---- documents ----------------------------------------------------------------------------------------------
    @staticmethod
    def get_doc(doctype, name=None):
        if isinstance(doctype, dict) and doctype.get("doctype") == "Notification Log":
            return _NotificationLog(doctype)
        if doctype == "User":                                       # people live in the control plane, not in a DocType
            if not _user_known(name): raise DoesNotExistError(f"User {name} does not exist")
            return SimpleNamespace(name=name, enabled=1, email=name)
        return _get_doc(doctype, name)

    @staticmethod
    def new_doc(doctype, **values):
        return _NotificationLog(values) if doctype == "Notification Log" else new_doc(doctype, **values)

    @staticmethod
    def get_list(doctype, filters=None, fields=None, order_by=None, limit_page_length=20, limit_start=0, limit=None, **_kw):
        if doctype == "User":
            who = (filters or {}).get("name") if isinstance(filters, dict) else None
            return [{"name": who, "enabled": 1}] if who and _user_known(who) else []
        if doctype == "Notification Log" and isinstance(filters, dict):
            filters = {_NL_FIELDS.get(k, k): v for k, v in filters.items()}
        if doctype == "Employee" and fields and "user_id" in fields:     # VeloraERP's Employee names the sign-in account `user_account`
            rows = Host.get_list(doctype, filters, ["user_account" if f == "user_id" else f for f in fields], order_by, limit_page_length, limit_start, limit)
            return [{**{k: v for k, v in r.items() if k != "user_account"}, "user_id": r.get("user_account")} for r in rows]
        want = limit if limit is not None else limit_page_length
        if want in (0, None):
            rows, start = [], int(limit_start or 0)
            while len(rows) < _ALL_ROWS:
                page = _get_list(doctype, filters=filters, fields=fields, order_by=order_by, limit=1000, offset=start)
                rows.extend(page); start += 1000
                if len(page) < 1000: break
            return rows
        return _get_list(doctype, filters=filters, fields=fields, order_by=order_by, limit=int(want), offset=int(limit_start or 0))

    get_all = get_list

    @staticmethod
    def get_count(doctype, filters=None) -> int:
        return _get_count(doctype, filters=filters)

    def get_single(self, doctype):
        """The settings record of a governance setup DocType: created with its defaults the first time it is read."""
        found = _get_list(doctype, filters=[["name", "=", SINGLE_NAME]], fields=["name"], limit=1, ignore_permissions=True)
        if found: return _get_doc(doctype, SINGLE_NAME, ignore_permissions=True)
        doc = new_doc(doctype, name=SINGLE_NAME)
        doc.insert(ignore_permissions=True)
        return doc


host = Host()
