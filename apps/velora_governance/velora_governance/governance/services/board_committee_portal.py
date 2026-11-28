"""Board and committee portal aggregation from caller-scoped datasets."""


def build_board_committee_portal(*, board=None, committee=None, meetings=None, agenda_items=None, actions=None, resolutions=None, audience_scope=None):
    scope = audience_scope or {}
    committee_name = committee
    meeting_rows = [dict(x) for x in (meetings or []) if not committee_name or x.get("committee") == committee_name]
    agenda_rows = [dict(x) for x in (agenda_items or []) if not committee_name or x.get("committee") == committee_name]
    action_rows = [dict(x) for x in (actions or []) if not committee_name or x.get("committee") == committee_name]
    resolution_rows = [dict(x) for x in (resolutions or []) if not committee_name or x.get("committee") == committee_name]
    upcoming = [x for x in meeting_rows if x.get("status") not in {"Completed", "Cancelled"}]
    return {"board": board, "committee": committee_name, "audience_scope": scope,
            "meetings": meeting_rows, "upcoming_meetings": upcoming, "agenda_items": agenda_rows,
            "actions": action_rows, "resolutions": resolution_rows,
            "summary": {"meetings": len(meeting_rows), "upcoming_meetings": len(upcoming),
                       "agenda_items": len(agenda_rows), "actions": len(action_rows), "resolutions": len(resolution_rows)},
            "permission_note": "Datasets must be pre-filtered using native Velora permissions; this service only aggregates supplied records."}
