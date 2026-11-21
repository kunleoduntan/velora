"""Export reports: permission check, themed Excel, audit-log entry."""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import insert

from .. import db
from ..db.system import export_log
from ..document.document import now
from ..exceptions import PermissionDenied
from ..meta.registry import registry
from ..permissions import get_session
from ..theme import current_excel_palette
from .excel import report_to_xlsx
from .runner import can_export, check_report_access, prepare_adhoc, run_adhoc, run_definition


def _finish(result, rdef, filters) -> tuple[bytes, str]:
    if not can_export(rdef):
        raise PermissionDenied(f"{get_session().user} has no 'export' permission for {rdef.ref_doctype or rdef.name!r}")
    data = report_to_xlsx(result, current_excel_palette(), user=get_session().user)
    with db.transaction() as conn:
        conn.execute(insert(export_log).values(
            name=secrets.token_hex(8), ref_doctype=rdef.ref_doctype or rdef.name, owner=get_session().user, creation=now(),
            scope="report", row_count=sum(1 for r in result.rows if r.type == "data"),
            detail={"report": rdef.name, "filters": {k: str(v) for k, v in (filters or {}).items()}}))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", result.title).strip("_") or "report"
    return data, f"{slug}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.xlsx"


def export_report(name: str, filters: dict | None) -> tuple[bytes, str]:
    rdef = registry.report(name)
    check_report_access(rdef)
    return _finish(run_definition(rdef, filters), rdef, filters)


def export_adhoc(spec: dict) -> tuple[bytes, str]:
    result = run_adhoc(spec)
    return _finish(result, prepare_adhoc(spec), {"spec": str(spec)[:300]})
