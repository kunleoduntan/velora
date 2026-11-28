"""Copy setup from one company to another: chart of accounts, masters, workflows and permissions (v1.11).

A company's setup is exported as a *bundle* (one JSON file), previewed against the receiving company (what is new, what is
already there) and applied in ONE transaction: either every selected section is copied or nothing is. Records that
already exist by name are never overwritten, so copying twice is harmless.

What a section contains comes from the apps (hook `setup_copy_provider`: a module with SECTIONS), plus three built into the
framework: workflows, permissions (roles, role/field permissions, row policies) and settings.  Only data that is the same kind of
thing in every company is copied (setup), never documents that were posted or submitted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import import_module

from fastapi import Body, Request
from sqlalchemy import insert, select

from . import db
from .exceptions import PermissionDenied, ValidationError
from .permissions import get_session

FORMAT = "velora-setup"
VERSION = 1

BUILTIN = [
    {"id": "workflows", "label": "Approval workflows", "description": "Every workflow definition: its states, who may take each action and the lock rules.", "kind": "workflows"},
    {"id": "permissions", "label": "Roles and permissions", "description": "Custom roles, role inheritance, DocType and field permissions, record scopes (row policies) and role conflicts.", "kind": "permissions"},
]


def _require_admin():
    s = get_session()
    if s.user != "Administrator" and "System Manager" not in s.roles:
        raise PermissionDenied("Only a System Manager can copy setup between companies")


def _providers():
    from .meta.registry import registry
    for app_name in registry.apps:
        try: hooks = import_module(f"{app_name}.hooks")
        except ModuleNotFoundError: continue
        path = getattr(hooks, "setup_copy_provider", None)
        if path:
            try: yield app_name, import_module(path)
            except Exception: continue


def sections() -> list[dict]:
    """What this company can copy. DocTypes that are missing here or submittable are left out (and said so)."""
    from .meta.registry import registry
    out = [{**b, "doctypes": [], "skipped": []} for b in BUILTIN]
    for app_name, mod in _providers():
        for sec in getattr(mod, "SECTIONS", []):
            if sec.get("settings"):                                   # one settings record: chosen fields and tables
                cfg = sec["settings"]
                if registry.exists(cfg["doctype"]):
                    out.append({"id": sec["id"], "label": sec["label"], "description": sec.get("description", ""), "kind": "settings", "app": app_name,
                                "doctypes": [], "skipped": [], "requires": sec.get("requires", []), "settings": cfg})
                continue
            usable, skipped = [], []
            for dt in sec["doctypes"]:
                if not registry.exists(dt): skipped.append({"doctype": dt, "reason": "not installed"}); continue
                meta = registry.get(dt)
                if getattr(meta, "is_submittable", False): skipped.append({"doctype": dt, "reason": "submittable documents are never copied"}); continue
                usable.append(dt)
            out.append({"id": sec["id"], "label": sec["label"], "description": sec.get("description", ""), "kind": "doctypes", "app": app_name,
                        "doctypes": usable, "skipped": skipped, "requires": sec.get("requires", [])})
    return out


def _section_map() -> dict:
    return {s["id"]: s for s in sections()}


def _chosen(ids) -> list[dict]:
    have = _section_map()
    ids = [str(i) for i in (ids or [])]
    if not ids: raise ValidationError("Choose at least one section to copy")
    unknown = [i for i in ids if i not in have]
    if unknown: raise ValidationError("Unknown section: " + ", ".join(unknown))
    return [sec for sid, sec in have.items() if sid in ids]            # always in the order the apps declare them: later sections link to earlier ones


# ------------------------------------------------------------------------------------------------------ export
_PERMISSION_TABLES = ("role_definition", "role_inheritance", "role_permission", "role_field_permission", "role_conflict", "row_policy")


def _plain(v):
    from datetime import date
    from decimal import Decimal
    if isinstance(v, datetime): return v.isoformat(sep=" ", timespec="seconds")
    if isinstance(v, date): return v.isoformat()
    if isinstance(v, Decimal): return str(v)
    return v


def _export_permissions() -> dict:
    from .db import system as S
    out = {}
    with db.transaction() as c:
        for name in _PERMISSION_TABLES:
            table = getattr(S, name)
            rows = [{k: _plain(v) for k, v in r.items()} for r in c.execute(select(table)).mappings()]
            if name == "role_definition": rows = [r for r in rows if not r.get("is_system")]
            out[name] = rows
    return out


def _settings_doc(cfg: dict):
    from . import get_doc, get_list
    rows = get_list(cfg["doctype"], fields=["name"], limit=1, ignore_permissions=True)
    return get_doc(cfg["doctype"], rows[0]["name"], ignore_permissions=True) if rows else None


def _export_settings(cfg: dict) -> dict:
    doc = _settings_doc(cfg)
    if doc is None: return {"doctype": cfg["doctype"], "fields": {}, "tables": {}}
    fields = {f: _plain(doc.get(f)) for f in cfg.get("fields", []) if doc.get(f) not in (None, "")}
    tables = {}
    for t in cfg.get("tables", []):
        child = doc.meta.get_field(t)
        cols = [f.fieldname for f in __import__("velora.meta.registry", fromlist=["registry"]).registry.get(child.options).value_fields]
        tables[t] = [{c: _plain(r.get(c)) for c in cols} for r in doc.get(t) or []]
    return {"doctype": cfg["doctype"], "fields": fields, "tables": tables}


def _apply_settings(cfg: dict, content: dict) -> int:
    """Update this company's settings record with the other company's policy values. Links to records that do not exist here are left alone."""
    doc = _settings_doc(cfg)
    if doc is None: raise ValidationError(f"{cfg['doctype']} has not been created in this company yet")
    changed = 0
    for name, value in (content.get("fields") or {}).items():
        if name not in cfg.get("fields", []): continue
        field = doc.meta.get_field(name)
        if field is None: continue
        if field.fieldtype == "Link" and not db.exists(field.options, value): continue
        if _plain(doc.get(name)) != _plain(value) and str(doc.get(name)) != str(value): doc.set(name, value); changed += 1
    for t, rows in (content.get("tables") or {}).items():
        if t not in cfg.get("tables", []): continue
        doc.set(t, rows); changed += len(rows)
    if changed: doc.save(ignore_permissions=True)
    return changed


def export_bundle(section_ids: list[str]) -> dict:
    _require_admin()
    from .dataimport import export_data
    from .workflows import list_definitions
    bundle = {"format": FORMAT, "version": VERSION, "created_on": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sections": {}}
    for sec in _chosen(section_ids):
        if sec["kind"] == "workflows":
            bundle["sections"][sec["id"]] = {"workflows": [{k: v for k, v in w.items() if k not in ("created_by", "created_on")} for w in list_definitions()]}
        elif sec["kind"] == "permissions":
            bundle["sections"][sec["id"]] = {"permissions": _export_permissions()}
        elif sec["kind"] == "settings":
            bundle["sections"][sec["id"]] = {"settings": _export_settings(sec["settings"])}
        else:
            data = {}
            for dt in sec["doctypes"]:
                payload, _, _, count = export_data(dt, "json", limit=50000)
                data[dt] = json.loads(payload)["data"] if count else []
            bundle["sections"][sec["id"]] = {"doctypes": data}
    return bundle


# ------------------------------------------------------------------------------------------------------ apply
def _check_bundle(bundle) -> dict:
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT or not isinstance(bundle.get("sections"), dict):
        raise ValidationError("That is not a Velora setup file. Export one from the other company's Setup Copy page.")
    if int(bundle.get("version") or 0) > VERSION:
        raise ValidationError("This setup file was made by a newer Velora. Update this company first.")
    return bundle


def _existing_names(doctype: str) -> set:
    from . import get_list
    return {r["name"] for r in get_list(doctype, fields=["name"], limit=1000000, ignore_permissions=True)}


def _parents_first(doctype: str, docs: list[dict]) -> list[dict]:
    """A tree (Account Group, Department...) is created from the top down, so a child never arrives before its parent."""
    from .meta.registry import registry
    meta = registry.get(doctype)
    self_links = [f.fieldname for f in meta.fields if f.fieldtype == "Link" and f.options == doctype]
    if not self_links: return docs
    names = {d["name"] for d in docs if d.get("name")}
    placed, ordered, pending = set(), [], list(docs)
    while pending:
        progress = False
        rest = []
        for d in pending:
            deps = [d.get(f) for f in self_links if d.get(f) and d.get(f) in names]
            if all(x in placed for x in deps):
                ordered.append(d); placed.add(d.get("name")); progress = True
            else: rest.append(d)
        if not progress: ordered.extend(rest); break
        pending = rest
    return ordered


def _clean(doctype: str, doc: dict) -> dict:
    """Leave out what the receiving company works out for itself (read-only and calculated fields), so a copy can never smuggle in a derived value."""
    from .meta.registry import registry
    meta = registry.get(doctype)
    derived = {f.fieldname for f in meta.fields if f.read_only and not f.is_layout}
    out = {k: v for k, v in doc.items() if k not in derived and k not in ("owner", "creation", "modified", "modified_by", "docstatus")}
    for t in meta.table_fields:
        if isinstance(out.get(t.fieldname), list) and t.options:
            out[t.fieldname] = [_clean(t.options, r) if isinstance(r, dict) else r for r in out[t.fieldname]]
    return out


def _same_workflow(a: dict, b: dict) -> bool:
    key = lambda w: json.dumps([w.get("doctype"), w.get("initial_state"), w.get("state_field"), w.get("states"), w.get("transitions"), int(bool(w.get("enabled", 1)))], sort_keys=True, default=str)
    return key(a) == key(b)


def _replaceable(existing: dict, incoming: dict) -> bool:
    """An inactive, never-used workflow of the same name is only a sample: the copied one replaces it (unless it is already identical)."""
    from . import workflows as _wf
    return _wf.is_unused_sample(existing["name"]) and not _same_workflow(existing, incoming)


def _plan(bundle: dict, section_ids: list[str]) -> list[dict]:
    """What would happen, per DocType / table, without writing anything."""
    from .meta.registry import registry
    _check_bundle(bundle)
    plan = []
    for sec in _chosen(section_ids):
        content = bundle["sections"].get(sec["id"])
        if content is None: raise ValidationError(f"The file does not contain {sec['label']!r}")
        if sec["kind"] == "workflows":
            from . import workflows as _wf
            have = {w["name"]: w for w in _wf.list_definitions()}
            for w in content.get("workflows", []):
                if not registry.exists(w["doctype"]): plan.append({"section": sec["id"], "item": w["name"], "kind": "workflow", "new": 0, "existing": 0, "blocked": f"DocType {w['doctype']} is not installed here"}); continue
                fresh = w["name"] not in have or _replaceable(have[w["name"]], w)          # an inactive, never-used sample is replaced; a live workflow is kept
                plan.append({"section": sec["id"], "item": w["name"], "kind": "workflow", "new": 1 if fresh else 0, "existing": 0 if fresh else 1,
                             **({"note": "replaces this company's inactive sample"} if w["name"] in have and fresh else {})})
        elif sec["kind"] == "settings":
            body = content.get("settings") or {}
            n = len([f for f in (body.get("fields") or {}) if f in sec["settings"].get("fields", [])]) + sum(len(r) for r in (body.get("tables") or {}).values())
            plan.append({"section": sec["id"], "item": sec["settings"]["doctype"], "kind": "settings", "new": 0, "existing": 0, "updates": n,
                         "note": f"updates {n} setting{'' if n == 1 else 's'} here with the other company's policy"})
        elif sec["kind"] == "permissions":
            for table, rows in (content.get("permissions") or {}).items():
                if table in _PERMISSION_TABLES: plan.append({"section": sec["id"], "item": table, "kind": "permissions", "new": len(rows), "existing": 0, "note": "added where missing"})
        else:
            for dt, docs in (content.get("doctypes") or {}).items():
                if dt not in sec["doctypes"]: continue
                have = _existing_names(dt)
                new = [d for d in docs if d.get("name") not in have]
                plan.append({"section": sec["id"], "item": dt, "kind": "doctype", "new": len(new), "existing": len(docs) - len(new)})
    return plan


def preview(bundle: dict, section_ids: list[str]) -> dict:
    _require_admin()
    plan = _plan(bundle, section_ids)
    return {"plan": plan, "new": sum(p["new"] for p in plan), "existing": sum(p["existing"] for p in plan), "blocked": [p for p in plan if p.get("blocked")]}


def _apply_permissions(rows_by_table: dict) -> int:
    from .db import system as S
    added = 0
    for name in _PERMISSION_TABLES:
        rows = rows_by_table.get(name) or []
        table = getattr(S, name)
        keys = [c.name for c in table.primary_key.columns]
        cols = {c.name: c for c in table.c}
        with db.transaction() as c:
            for r in rows:
                values = {k: v for k, v in r.items() if k in cols}
                for k, col in cols.items():
                    if k in values and values[k] is not None and col.type.__class__.__name__ == "DateTime" and isinstance(values[k], str):
                        values[k] = datetime.fromisoformat(values[k])
                if c.execute(select(table).where(*[table.c[k] == values.get(k) for k in keys])).first(): continue
                c.execute(insert(table).values(**values)); added += 1
    return added


def apply_bundle(bundle: dict, section_ids: list[str]) -> dict:
    """Copy the chosen sections into this company, all or nothing."""
    _require_admin()
    from .dataimport import Options, import_file
    from .workflows import list_definitions, save_definition
    plan = _plan(bundle, section_ids)
    blocked = [p for p in plan if p.get("blocked")]
    if blocked: raise ValidationError("Cannot copy: " + "; ".join(f"{p['item']} ({p['blocked']})" for p in blocked))
    done = []
    with db.transaction():
        for sec in _chosen(section_ids):
            content = bundle["sections"][sec["id"]]
            if sec["kind"] == "workflows":
                from . import workflows as _wf
                have = {w["name"]: w for w in list_definitions()}
                for w in content.get("workflows", []):
                    if w["name"] in have and not _replaceable(have[w["name"]], w): continue
                    save_definition(w, system=True); done.append({"section": sec["id"], "item": w["name"], "created": 1})
            elif sec["kind"] == "settings":
                n = _apply_settings(sec["settings"], content.get("settings") or {})
                done.append({"section": sec["id"], "item": sec["settings"]["doctype"], "created": 0, "updated": n})
            elif sec["kind"] == "permissions":
                n = _apply_permissions(content.get("permissions") or {})
                done.append({"section": sec["id"], "item": "permissions", "created": n})
            else:
                for dt in sec["doctypes"]:
                    docs = (content.get("doctypes") or {}).get(dt) or []
                    have = _existing_names(dt)
                    new = _parents_first(dt, [_clean(dt, d) for d in docs if d.get("name") not in have])
                    if not new: done.append({"section": sec["id"], "item": dt, "created": 0}); continue
                    payload = json.dumps({"doctype": dt, "data": new}).encode()
                    from .permissions import memoized
                    with memoized():          # one DocType at a time: its roles, workflows and scripts are read once, not once per record
                        report = import_file(dt, payload, f"{dt}.json", Options(mode="insert", keep_names=True, atomic=True), log=False)
                    if report.failed:
                        first = (report.errors or [{}])[0]
                        raise ValidationError(f"Copy stopped at {dt}: {report.failed} record(s) could not be created ({first.get('message') or first or 'see the import report'}). Nothing was copied.")
                    done.append({"section": sec["id"], "item": dt, "created": report.created})
    try:
        from .activity import record_event
        record_event("setup_copy", "Setup copied from another company", summary=", ".join(sorted({d["section"] for d in done})), source="automation",
                     metadata={"created": sum(d["created"] for d in done)})
    except Exception:
        pass
    return {"copied": done, "created": sum(d["created"] for d in done)}


def install_routes(app, run):
    @app.get("/api/setup-copy/sections")
    def setup_copy_sections(request: Request): return run(request, lambda: (_require_admin(), sections())[1])
    @app.post("/api/setup-copy/export")
    def setup_copy_export(request: Request, body: dict = Body(...)): return run(request, lambda: export_bundle(body.get("sections") or []))
    @app.post("/api/setup-copy/preview")
    def setup_copy_preview(request: Request, body: dict = Body(...)): return run(request, lambda: preview(body.get("bundle"), body.get("sections") or []))
    @app.post("/api/setup-copy/apply")
    def setup_copy_apply(request: Request, body: dict = Body(...)): return run(request, lambda: apply_bundle(body.get("bundle"), body.get("sections") or []))
