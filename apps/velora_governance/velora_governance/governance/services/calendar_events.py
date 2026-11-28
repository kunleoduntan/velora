from velora import get_doc, get_list, new_doc


def create_event(*, event_type_name, title, entity, board=None, event_date=None, owner=None,
                reminder_days=None, related_doctype=None, related_record=None, status="Open"):
    types = get_list("Governance Event Type", fields=["name", "event_type_name", "default_reminder_days"], limit=1000, ignore_permissions=True)
    event_type = next((row for row in types if row.get("event_type_name") == event_type_name), None)
    if not event_type or not event_date:
        return None
    event = new_doc("Governance Calendar Event", event_title=title, event_type=event_type["name"], governance_entity=entity,
        board=board, event_date=event_date, responsible_person=owner,
        reminder_days=reminder_days if reminder_days is not None else event_type.get("default_reminder_days"),
        event_status=status, related_doctype=related_doctype, related_record=related_record)
    event.insert(ignore_permissions=True)
    return event.name


def sync_event(name, *, title=None, entity=None, board=None, event_date=None, status=None,
               related_doctype=None, related_record=None, owner=None):
    if not name:
        return
    event = get_doc("Governance Calendar Event", name, ignore_permissions=True)
    if title is not None: event.event_title = title
    if entity is not None: event.governance_entity = entity
    if board is not None: event.board = board
    if event_date is not None: event.event_date = event_date
    if status is not None: event.event_status = status
    if related_doctype is not None: event.related_doctype = related_doctype
    if related_record is not None: event.related_record = related_record
    if owner is not None: event.responsible_person = owner
    event.save(ignore_permissions=True)
