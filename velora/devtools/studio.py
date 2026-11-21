"""Read-only developer catalog and metadata inspection for the Velora Developer Studio.

This module deliberately exposes application declarations, not executable source or secrets.
Company-specific metadata is resolved from the currently bound site's registry.
"""
from __future__ import annotations

from ..meta.registry import registry


def catalog() -> dict:
    apps = []
    for app in registry.apps:
        doctypes = sorted(d.name for d in registry.all() if d.app == app)
        apps.append({"name": app, "doctype_count": len(doctypes), "doctypes": doctypes})
    doc_events = []
    for doctype, events in sorted(registry._doc_events.items()):
        for event, handlers in sorted(events.items()):
            doc_events.append({"doctype": doctype, "event": event, "handlers": list(handlers)})
    jobs = registry.job_handlers()
    scheduler = {freq: list(tasks) for freq, tasks in registry._scheduler.items()}
    pg_objects = [{"app": item.get("app"), "name": item.get("name"), "type": item.get("type")}
                  for item in registry.pg_objects()]
    return {"apps": apps, "doc_events": doc_events,
            "job_handlers": [{"name": name, "handler": handler} for name, handler in sorted(jobs.items())],
            "scheduler_events": scheduler, "database_objects": pg_objects,
            "doctype_count": len(registry.all())}


def inspect_doctype(name: str) -> dict:
    meta = registry.get(name)
    return {
        "name": meta.name, "app": meta.app, "module": meta.module,
        "controller_module": meta.controller_module,
        "has_controller": bool(meta.controller_module),
        "is_submittable": meta.is_submittable, "is_child": meta.istable,
        "track_changes": meta.track_changes,
        "fields": [f.to_dict() for f in meta.fields],
        "permissions": [p.__dict__.copy() for p in meta.permissions],
        "api": {
            "metadata": f"GET /api/meta/{name}",
            "list": f"GET /api/resource/{name}",
            "create": f"POST /api/resource/{name}",
            "read": f"GET /api/resource/{name}/{{name}}",
            "update": f"PUT /api/resource/{name}/{{name}}",
            "delete": f"DELETE /api/resource/{name}/{{name}}",
            "client_script": f"GET /api/client_script/{name}?kind=form",
        },
    }
