"""v4.8 audience-scoped Board/Committee workspace model."""

DEFAULT_SECTIONS = ("overview", "meetings", "agenda", "papers", "actions", "resolutions", "calendar")


def build_portal_workspace(*, audience_type, audience_id, data=None, permitted_sections=None, permission_checked=False):
    data = data or {}
    sections = list(permitted_sections or DEFAULT_SECTIONS)
    if not permission_checked:
        return {"available": False, "reason": "permission_check_required", "sections": {}, "version": "4.8.0"}
    if audience_type not in {"board", "committee"} or not audience_id:
        return {"available": False, "reason": "invalid_audience_scope", "sections": {}, "version": "4.8.0"}
    output = {}
    for section in sections:
        if section not in DEFAULT_SECTIONS:
            continue
        rows = list(data.get(section) or [])
        # Strict scope: rows must explicitly match audience id/type unless section is overview.
        if section != "overview":
            rows = [row for row in rows if row.get("audience_id") == audience_id and row.get("audience_type", audience_type) == audience_type]
        output[section] = rows
    return {"available": True, "audience_type": audience_type, "audience_id": audience_id,
            "sections": output, "section_count": len(output), "version": "4.8.0"}
