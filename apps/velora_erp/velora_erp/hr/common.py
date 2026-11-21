"""Small helpers shared by the HR controllers."""


def decided_now(doc, field):
    """True when `field` was just changed (or the record is new), so an approver or closer should be stamped.

    A later save of an already-decided record (a typo fixed, a note added) must not replace who approved it and when.
    """
    old = getattr(doc, "_old", None)
    if not old:
        return True
    return old.get(field) != getattr(doc, field, None)
