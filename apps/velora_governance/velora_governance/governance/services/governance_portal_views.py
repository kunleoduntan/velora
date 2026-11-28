"""Role-configurable governance portal view definitions (permission-neutral)."""
DEFAULT_PORTAL_SECTIONS = ["overview", "actions", "risks", "compliance", "reports", "meetings", "controls"]


def build_portal_view(role, *, role_config=None, available_sections=None, user_context=None):
    """Return a view definition; actual record permissions remain native framework-owned."""
    config = role_config or {}
    sections = list(available_sections or DEFAULT_PORTAL_SECTIONS)
    role_key = str(role or "").strip()
    role_cfg = config.get(role_key, {}) if isinstance(config, dict) else {}
    configured = role_cfg.get("sections") if isinstance(role_cfg, dict) else None
    visible = [s for s in (configured or sections) if s in sections]
    return {"role": role_key, "sections": visible, "section_count": len(visible),
            "view_configured": bool(role_cfg), "permission_enforcement": "native_framework_required",
            "user_context": user_context or {},
            "warning": "This view configuration is not an authorization grant. Apply native permission checks to every data request."}
