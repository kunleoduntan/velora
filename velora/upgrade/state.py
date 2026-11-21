"""What version is a database at, and may the running code use it?

Rule: bug-fix releases (same MAJOR.MINOR) never need a data upgrade. A newer MAJOR.MINOR does, and until `velora upgrade` has run
the database refuses to serve (HTTP 503 "upgrade pending") - new code must never run against an old schema. Data newer than the code
(a downgrade) is refused too.
"""
from __future__ import annotations

import time

from ..settings import get_setting, set_setting
from .versions import app_version, code_version, minor_key

FRAMEWORK_KEY = "framework_version"
_TTL = 5.0


def recorded_version() -> str | None:
    return get_setting(FRAMEWORK_KEY)


def stamp(version: str | None = None) -> None:
    """Record that this database is now at `version` (default: the running code), including every installed app's version."""
    from sqlalchemy import update

    from .. import db, site as site_mod
    from ..db.system import installed_app
    set_setting(FRAMEWORK_KEY, version or code_version())
    with db.transaction() as conn:
        for app in site_mod.current().installed_apps():
            conn.execute(update(installed_app).where(installed_app.c.name == app).values(version=app_version(app)))
    site_mod.current().gate_cache = None


def gate_state(recorded: str | None, code: str | None = None) -> tuple[str, str | None]:
    code = code or code_version()
    if recorded is None:
        return "upgrade_pending", None
    a, b = minor_key(code), minor_key(recorded)
    return ("ok" if a == b else "upgrade_pending" if a > b else "downgrade"), recorded


def check_site(site) -> tuple[str, str | None]:
    """Cached per Site (a few seconds) so every request does not hit the database."""
    from .. import site as site_mod
    cached = getattr(site, "gate_cache", None)
    if cached and time.monotonic() - cached[0] < _TTL:
        return cached[1]
    with site_mod.use(site):
        state = gate_state(recorded_version())
    site.gate_cache = (time.monotonic(), state)
    return state


def gate_message(state: str, recorded: str | None) -> str:
    if state == "downgrade":
        return (f"This database is at version {recorded}, newer than the installed code ({code_version()}). "
                "Install the newer release, or restore a backup taken before the upgrade.")
    return "This database needs an upgrade before it can be used. An administrator must run `velora upgrade`."
