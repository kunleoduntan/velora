"""Trusted append-only fixed asset history writer used by lifecycle transactions."""
from velora import new_doc


def record_asset_history(asset, event_type, event_date, source_doctype, source_name,
                         from_values=None, to_values=None, reason=None):
    log = new_doc(
        "Fixed Asset History Log", asset=asset.name, event_type=event_type,
        event_date=event_date, source_doctype=source_doctype,
        source_name=source_name, from_values=from_values or {},
        to_values=to_values or {}, reason=reason or "",
    )
    log.flags.trusted_source = True
    log.insert(ignore_permissions=True)
    return log
