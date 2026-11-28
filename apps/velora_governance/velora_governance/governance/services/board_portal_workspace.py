"""Board/committee workspace data shaping. Authorization must be performed natively first."""

def build_board_workspace(*, audience_id, audience_type="board", meetings=None, agenda_items=None,
                         actions=None, resolutions=None, documents=None, allowed_document_ids=None):
    if not audience_id:
        return {"status": "rejected", "reason": "audience_id_required"}
    allowed = set(allowed_document_ids or [])
    meetings = [dict(x) for x in (meetings or []) if x.get("audience_id") in {None, audience_id}]
    meeting_ids = {m.get("id") for m in meetings}
    agendas = [dict(x) for x in (agenda_items or []) if x.get("meeting_id") in meeting_ids]
    action_rows = [dict(x) for x in (actions or []) if x.get("audience_id") in {None, audience_id}]
    resolution_rows = [dict(x) for x in (resolutions or []) if x.get("audience_id") in {None, audience_id}]
    doc_rows = [dict(x) for x in (documents or []) if x.get("id") in allowed]
    return {"status": "ok", "audience_id": audience_id, "audience_type": audience_type,
            "meetings": meetings, "agenda_items": agendas, "actions": action_rows,
            "resolutions": resolution_rows, "documents": doc_rows,
            "summary": {"meetings": len(meetings), "agenda_items": len(agendas),
                       "open_actions": sum(1 for a in action_rows if a.get("status") not in {"completed", "closed"}),
                       "resolutions": len(resolution_rows), "documents": len(doc_rows)}}
