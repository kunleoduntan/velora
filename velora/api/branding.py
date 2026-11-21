"""Company-local application branding and navigation configuration."""
from __future__ import annotations

import re
from fastapi import Body, FastAPI, Request

from ..exceptions import PermissionDenied, ValidationError
from ..meta.registry import registry
from ..permissions import get_session, has_permission
from ..settings import get_setting, set_setting

KEY = "application.branding"
SAFE_ICON = re.compile(r"^[a-z0-9-]{1,40}$")


def _manager() -> bool:
    session = get_session()
    return session.user == "Administrator" or "System Manager" in session.roles


def _defaults() -> dict:
    return {"app_name": "Velora", "tagline": "", "logo_url": "", "favicon_url": "", "navigation": []}


def _clean(body: dict) -> dict:
    if not isinstance(body, dict):
        raise ValidationError("Branding configuration must be an object")
    allowed = {"app_name", "tagline", "logo_url", "favicon_url", "navigation"}
    extra = set(body) - allowed
    if extra:
        raise ValidationError(f"Unsupported branding property: {', '.join(sorted(extra))}")
    out = _defaults()
    for key, limit in (("app_name", 60), ("tagline", 120), ("logo_url", 500), ("favicon_url", 500)):
        value = body.get(key, out[key])
        if not isinstance(value, str) or len(value) > limit or any(ord(ch) < 32 for ch in value):
            raise ValidationError(f"{key} must be text of at most {limit} characters")
        value = value.strip()
        if key in {"logo_url", "favicon_url"} and value and not (value.startswith("/") and not value.startswith("//") or value.startswith("https://")):
            raise ValidationError(f"{key} must be a site-relative path or HTTPS URL")
        out[key] = value
    navigation = body.get("navigation", [])
    if not isinstance(navigation, list) or len(navigation) > 30:
        raise ValidationError("navigation must be a list of at most 30 menu groups")
    seen = set()
    groups = []
    total = 0
    for group in navigation:
        if not isinstance(group, dict) or set(group) - {"label", "items"}:
            raise ValidationError("Each navigation group must contain only label and items")
        label = group.get("label")
        items = group.get("items")
        if not isinstance(label, str) or not label.strip() or len(label) > 50 or not isinstance(items, list):
            raise ValidationError("Each navigation group needs a label and an item list")
        clean_items = []
        for item in items:
            total += 1
            if total > 200:
                raise ValidationError("Navigation may contain at most 200 items")
            if not isinstance(item, dict) or set(item) - {"doctype", "label", "icon"}:
                raise ValidationError("Navigation items may contain only doctype, label and icon")
            doctype = item.get("doctype")
            caption = item.get("label", "")
            icon = item.get("icon", "")
            if not isinstance(doctype, str) or not doctype or doctype in seen:
                raise ValidationError("Each navigation DocType must be valid and appear only once")
            if not isinstance(caption, str) or len(caption) > 60:
                raise ValidationError("Navigation labels must be text of at most 60 characters")
            if not isinstance(icon, str) or (icon and not SAFE_ICON.fullmatch(icon)):
                raise ValidationError("Navigation icons must use a lowercase kebab-case icon name")
            if not registry.exists(doctype):
                raise ValidationError(f"Unknown DocType in navigation: {doctype}")
            meta = registry.get(doctype)
            if meta.istable or not has_permission(meta, "read"):
                raise PermissionDenied(f"You cannot add {doctype} to the navigation")
            seen.add(doctype)
            clean_items.append({"doctype": doctype, "label": caption.strip(), "icon": icon})
        groups.append({"label": label.strip(), "items": clean_items})
    out["navigation"] = groups
    return out


def install_routes(app: FastAPI, scope, run):
    @app.get("/api/application-branding")
    def get_branding(request: Request):
        def fn():
            cfg = get_setting(KEY, {}) or {}
            merged = {**_defaults(), **cfg}
            available = [{"name": m.name, "module": m.module} for m in registry.all()
                         if not m.istable and has_permission(m, "read")]
            return {"branding": merged, "available_doctypes": available, "can_edit": _manager()}
        return run(request, fn)

    @app.put("/api/application-branding")
    def put_branding(request: Request, body: dict = Body(...)):
        def fn():
            if not _manager():
                raise PermissionDenied("Only a System Manager can change application branding")
            clean = _clean(body)
            set_setting(KEY, clean)
            return {"branding": clean, "saved": True}
        return run(request, fn)
