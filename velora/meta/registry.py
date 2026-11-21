"""DocType registry: discovers installed apps, loads + cross-validates metadata.

App layout (discovered automatically):

    <app>/<module>/doctype/<doctype_name>/<doctype_name>.json
    <app>/<module>/doctype/<doctype_name>/<doctype_name>.py   (controller, optional)
    <app>/hooks.py                                           (optional: doc_events)

Controllers are trusted code loaded from installed packages - never evaluated
from database content.
"""
from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

from ..exceptions import DoesNotExistError, MetaError
from .spec import DocType


def pascal(name: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[^A-Za-z0-9]+", name) if p)


def cross_check(doctypes: dict) -> list[str]:
    """Rules that span DocTypes (link targets, child tables, reserved names). Also used by the DocType Creator BEFORE it writes anything."""
    from ..document.document import Document

    reserved = {n for n in dir(Document) if not n.startswith("_")} | {"doctype", "meta", "flags"}
    errors = []
    for dt in doctypes.values():
        for f in dt.fields:
            if f.fieldname in reserved:
                errors.append(f"{dt.name}.{f.fieldname}: reserved name")
            if f.fieldtype == "Link" and f.options not in doctypes and f.options != "DocType":     # "DocType" is the virtual catalogue of document types
                errors.append(f"{dt.name}.{f.fieldname}: Link target {f.options!r} is not a DocType")
            if f.is_table:
                target = doctypes.get(f.options)
                if not target:
                    errors.append(f"{dt.name}.{f.fieldname}: Table target {f.options!r} is not a DocType")
                elif not target.istable:
                    errors.append(f"{dt.name}.{f.fieldname}: {f.options!r} must be a child table (istable)")
    return errors


class Registry:
    def __init__(self, site=None):
        self.site = site
        self.clear()

    def clear(self):
        self._doctypes: dict[str, DocType] = {}
        self._apps: list[str] = []
        self._controllers: dict[str, type] = {}
        self._doc_events: dict[str, dict[str, list[str]]] = {}
        self._resolved: dict[str, object] = {}
        self._reports: dict = {}
        self._scheduler: dict[str, list[str]] = {}
        self._job_handlers: dict[str, str] = {}
        self._pg_objects: list[dict] = []
        self._app_extensions: dict[str, dict] = {}

    # ---- loading ----------------------------------------------------------
    def load(self, apps: list[str]):
        self.clear()
        for app in apps:
            self._load_app(app)
        self._cross_validate()

    def table_collision(self, name: str, ignore: tuple = (), extra_names: tuple = ()) -> str | None:
        """The name of another DocType (loaded, or listed in `extra_names`, e.g. archived ones that still own their table) that maps to the SAME database table as `name`, or None.

        Table names are derived lossily ("Sales Order" and "Sales-Order" are both tab_sales_order), so two different spellings would silently share one table."""
        from ..db.tables import table_name
        mine = table_name(name)
        for other in list(self._doctypes) + list(extra_names):
            if other != name and other not in ignore and table_name(other) == mine:
                return other
        return None

    def load_company_doctypes(self, definitions: list[dict] | None, strict: bool = True):
        """Atomically load site/company-local DocType metadata from this company's database.

        strict=True  (when saving): any problem raises and nothing changes.
        strict=False (when a company LOADS): a definition that is invalid, or clashes with an application DocType or another object's table, is skipped and listed in
        `company_conflicts`, so one bad object cannot stop the whole company from starting."""
        previous = self._doctypes
        previous_conflicts = getattr(self, "company_conflicts", [])
        candidate = {name: meta for name, meta in previous.items() if meta.app != "company"}
        conflicts: list[dict] = []
        self._doctypes = candidate
        try:
            for raw in definitions or []:
                label = raw.get("name", "") if isinstance(raw, dict) else str(raw)
                try:
                    meta = DocType.from_dict(raw, app="company", source=f"company://{label}")
                    if meta.name in self._doctypes:
                        raise MetaError(f"Company DocType {meta.name!r} conflicts with an installed application DocType")
                    clash = self.table_collision(meta.name)
                    if clash:
                        raise MetaError(f"Company DocType {meta.name!r} would share its database table with {clash!r}")
                except Exception as exc:  # noqa: BLE001
                    if strict:
                        raise
                    conflicts.append({"name": label, "reason": str(exc)})
                    continue
                self._doctypes[meta.name] = meta
            try:
                self._cross_validate()
            except Exception as exc:  # noqa: BLE001
                if strict:
                    raise
                conflicts.append({"name": "(relationships)", "reason": str(exc)})
                self._doctypes = {n: m for n, m in self._doctypes.items() if m.app != "company"}
        except Exception:
            self._doctypes = previous
            self.company_conflicts = previous_conflicts
            raise
        self.company_conflicts = conflicts

    def _load_app(self, app: str):
        pkg = importlib.import_module(app)
        root = Path(pkg.__file__).parent
        self._apps.append(app)
        from ..app_runtime import inspect_app_extensions
        self._app_extensions[app] = inspect_app_extensions(app)
        for path in sorted(root.rglob("doctype/*/*.json")):
            if path.stem != path.parent.name:
                continue
            meta = DocType.from_dict(json.loads(path.read_text()), app=app, source=str(path))
            if meta.name in self._doctypes:
                raise MetaError(f"DocType {meta.name!r} defined twice ({self._doctypes[meta.name].source} and {path})")
            meta.controller_module = ".".join(path.parent.relative_to(root.parent).parts) + "." + path.stem
            self._doctypes[meta.name] = meta
        from ..reporting.definition import ReportDef
        for path in sorted(root.rglob("report/*/*.json")):
            if path.stem != path.parent.name:
                continue
            rd = ReportDef.from_dict(json.loads(path.read_text()), app=app, source=str(path))
            if rd.name in self._reports:
                raise MetaError(f"Report {rd.name!r} defined twice ({self._reports[rd.name].source} and {path})")
            rd.controller_module = ".".join(path.parent.relative_to(root.parent).parts) + "." + path.stem
            self._reports[rd.name] = rd
        try:
            hooks = importlib.import_module(f"{app}.hooks")
        except ModuleNotFoundError as e:
            if e.name != f"{app}.hooks":
                raise
            return
        for o in getattr(hooks, "pg_objects", []) or []:
            self._pg_objects.append({**o, "app": app})
        for freq, tasks in getattr(hooks, "scheduler_events", {}).items():
            self._scheduler.setdefault(freq, []).extend([tasks] if isinstance(tasks, str) else tasks)
        declared_jobs = getattr(hooks, "job_handlers", []) or []
        if isinstance(declared_jobs, dict):
            self._job_handlers.update({str(name): str(path) for name, path in declared_jobs.items()})
        else:
            for path in declared_jobs:
                self._job_handlers[str(path)] = str(path)
        for dt, events in getattr(hooks, "doc_events", {}).items():
            for event, handlers in events.items():
                lst = self._doc_events.setdefault(dt, {}).setdefault(event, [])
                lst.extend([handlers] if isinstance(handlers, str) else handlers)

    def _cross_validate(self):
        errors = cross_check(self._doctypes)
        errors += self._validate_reports()
        if errors:
            raise MetaError("Metadata cross-validation failed:\n  - " + "\n  - ".join(errors), details=errors)

    def _validate_reports(self) -> list:
        errors = []
        for r in self._reports.values():
            tag = f"Report {r.name!r}"
            dt = self._doctypes.get(r.ref_doctype) if r.ref_doctype else None
            if r.ref_doctype and dt is None:
                errors.append(f"{tag}: ref_doctype {r.ref_doctype!r} is not a DocType")
            for f in r.filters:
                if f.fieldtype == "Link" and f.options not in self._doctypes:
                    errors.append(f"{tag}: filter {f.fieldname} links to unknown DocType {f.options!r}")
            if r.type == "summary" and dt is not None:
                cols = set(dt.column_names())
                for g in r.group_by:
                    if g not in cols:
                        errors.append(f"{tag}: group_by field {g!r} does not exist on {dt.name}")
                for m in r.measures:
                    fld = dt.get_field(m.get("field")) if m.get("field") else None
                    if m.get("fn") != "count" and (fld is None or fld.fieldtype not in ("Int", "Float", "Currency")):
                        errors.append(f"{tag}: measure {m.get('fn')}({m.get('field')}) needs a numeric field on {dt.name}")
                if r.date_field and not (dt.get_field(r.date_field) and dt.get_field(r.date_field).fieldtype in ("Date", "Datetime")) and r.date_field not in ("creation", "modified"):
                    errors.append(f"{tag}: date_field {r.date_field!r} is not a Date/Datetime field")
                if r.date_bucket and r.date_field not in r.group_by:
                    errors.append(f"{tag}: date_bucket needs date_field in group_by")
            if r.type == "script":
                try:
                    mod = importlib.import_module(r.controller_module)
                    if not callable(getattr(mod, "execute", None)):
                        errors.append(f"{tag}: {r.controller_module} must define execute(filters)")
                except ModuleNotFoundError as e:
                    if e.name == r.controller_module:
                        errors.append(f"{tag}: script report needs {r.controller_module.rsplit('.', 1)[-1]}.py with execute(filters)")
                    else:
                        raise
        return errors

    # ---- lookups ----------------------------------------------------------
    def get(self, doctype: str) -> DocType:
        try:
            base = self._doctypes[doctype]
        except KeyError:
            raise DoesNotExistError(f"DocType {doctype!r} does not exist") from None
        from .extensions import effective_meta
        if self.site is not None:
            from ..site import current, use
            try:
                active = current()
            except RuntimeError:
                active = None
            if active is not self.site:
                with use(self.site):
                    return effective_meta(base)
        return effective_meta(base)

    def report(self, name: str):
        try:
            return self._reports[name]
        except KeyError:
            raise DoesNotExistError(f"Report {name!r} does not exist") from None

    def reports(self) -> list:
        return list(self._reports.values())

    def report_fn(self, name: str):
        return importlib.import_module(self.report(name).controller_module).execute

    def exists(self, doctype: str) -> bool:
        return doctype in self._doctypes

    def all(self) -> list[DocType]:
        return [self.get(name) for name in self._doctypes]

    @property
    def apps(self):
        return list(self._apps)

    def links_to(self, doctype: str):
        """(DocType, field) pairs that hold a Link to `doctype`."""
        return [(d, f) for d in self._doctypes.values() for f in d.fields if f.fieldtype == "Link" and f.options == doctype]

    # ---- controllers & hooks ---------------------------------------------
    def controller_for(self, doctype: str) -> type:
        from ..document.document import Document

        if doctype in self._controllers:
            return self._controllers[doctype]
        meta = self.get(doctype)
        cls = Document
        try:
            if meta.app == "company":
                raise ModuleNotFoundError(name=meta.controller_module)
            mod = importlib.import_module(meta.controller_module)
        except ModuleNotFoundError as e:
            if e.name != meta.controller_module:
                raise
        else:
            cls = getattr(mod, pascal(doctype), None)
            if cls is None or not issubclass(cls, Document):
                raise MetaError(f"{meta.controller_module} must define class {pascal(doctype)}(Document)")
        self._controllers[doctype] = cls
        return cls

    def pg_objects(self) -> list[dict]:
        return list(self._pg_objects)

    def app_extensions(self) -> list[dict]:
        """Company/site-local extension manifests for installed applications."""
        return [dict(self._app_extensions[name]) for name in self._apps if name in self._app_extensions]

    def scheduler_tasks(self, freq: str) -> list[str]:
        return list(self._scheduler.get(freq, []))

    def job_handlers(self) -> dict[str, str]:
        """Registered app-owned background job handlers (name -> dotted callable path)."""
        return dict(self._job_handlers)

    def event_handlers(self, doctype: str, event: str):
        out = []
        for key in (doctype, "*"):
            for path in self._doc_events.get(key, {}).get(event, []):
                if path not in self._resolved:
                    mod, _, fn = path.rpartition(".")
                    self._resolved[path] = getattr(importlib.import_module(mod), fn)
                out.append(self._resolved[path])
        return out



class _RegistryProxy:
    """`registry` always means "the current site's registry" (each site has its own installed apps)."""

    def __getattr__(self, name):
        from ..site import current
        return getattr(current().registry, name)


registry = _RegistryProxy()
