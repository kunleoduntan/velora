"""Naming Series Rule: company-chosen numbering for any series-numbered document type."""
import re
from datetime import date

from sqlalchemy import select

from velora import Document, db, throw
from velora.db.system import series
from velora.meta.registry import registry
from velora.exceptions import DoesNotExistError
from velora.naming import RULES_KEY, clear_rules_cache, resolve_prefix
from velora.settings import get_setting, set_setting

PATTERN = re.compile(r"^(?P<prefix>[A-Za-z0-9_/\-]*(?:\.(?:YYYY|YY|MM|DD)\.[A-Za-z0-9_/\-]*)*)\.(?P<hashes>#{3,12})$")


def _sync():
    from velora import get_list
    rules = {r["document_type"]: r["pattern"] for r in get_list("Naming Series Rule", filters={"enabled": 1},
                                                              fields=["document_type", "pattern"], limit=1000, ignore_permissions=True)}
    set_setting(RULES_KEY, rules)
    clear_rules_cache()


class NamingSeriesRule(Document):
    def validate(self):
        self.document_type = (self.document_type or "").strip()
        self.pattern = (self.pattern or "").strip()
        try:
            dt = registry.get(self.document_type) if self.document_type else None
        except DoesNotExistError:
            dt = None
        if not dt:
            throw(f"{self.document_type!r} is not a known document type. Use its exact name, for example Sales Invoice.")
        if dt.istable:
            throw("Child tables cannot have a naming series.")
        auto = dt.autoname or ""
        if auto.startswith("field:") or auto == "prompt":
            throw(f"{dt.name} is named from {'a field' if auto.startswith('field:') else 'what the user types'}; a series cannot replace that.")
        m = PATTERN.match(self.pattern)
        if not m:
            throw("Pattern must be a prefix, optional date tokens (.YYYY. .YY. .MM. .DD.) and a counter of 3 to 12 hashes, e.g. PAY-.YYYY.-.#####")
        prefix = resolve_prefix(m.group("prefix"), date.today())
        with db.transaction() as conn:
            current = conn.execute(select(series.c.current).where(series.c.name == prefix)).scalar() or 0
        self.example = f"{prefix}{current + 1:0{len(m.group('hashes'))}d}"

    def on_update(self):
        _sync()

    def after_delete(self):
        _sync()
