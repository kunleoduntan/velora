"""What Velora runs on. ONE place for the supported Python, PostgreSQL and operating systems, used by `velora doctor`, the database setup and the docs.

Honesty about evidence: the code is tested on Python 3.10, 3.12 and 3.14 and on PostgreSQL 16. Operating systems are classified from what each ships
(Python and PostgreSQL versions) and what the installer does about it; only the system the tests ran on can be called tested.
"""
from __future__ import annotations

import sys

from .exceptions import VeloraError

MIN_PYTHON = (3, 10)
TESTED_PYTHON = ("3.10", "3.12", "3.14")
MIN_POSTGRES = 13                      # DROP DATABASE ... WITH (FORCE), generated columns, EXECUTE FUNCTION triggers, pg_trgm word similarity
RECOMMENDED_POSTGRES = 15              # older ones are near end of life
PGDG_APT = "https://apt.postgresql.org"


class UnsupportedPostgres(VeloraError):
    status_code = 500


# name -> (status, what the installer does)
UBUNTU = {
    "18.04": ("eol", "End of life since 2023 and ships Python 3.6 and PostgreSQL 10. Fine for DEVELOPMENT with install-dev.sh (a private Python is downloaded); do not run a production server on it. Upgrade: do-release-upgrade to 20.04, then 22.04."),
    "20.04": ("works", "Standard support ended in 2025. install.sh adds the official PostgreSQL repository (the system has 12) and a private Python (the system has 3.8)."),
    "22.04": ("supported", "Ships Python 3.10 (works as is) and PostgreSQL 14 (works as is; the installer can use the official repository for a newer one)."),
    "24.04": ("supported", "Ships Python 3.12 and PostgreSQL 16. The system the test suite ran on."),
    "26.04": ("supported", "Ships PostgreSQL 18 and Python 3.13/3.14 (Velora is tested on 3.14)."),
}
DEBIAN = {
    "11": ("works", "Ships Python 3.9 and PostgreSQL 13: install.sh adds a private Python."),
    "12": ("supported", "Ships Python 3.11 and PostgreSQL 15."),
    "13": ("supported", "Ships Python 3.13 and PostgreSQL 17."),
}


def python_status(v=None) -> tuple[str, str, str]:
    """(status, detail, fix)"""
    v = v or sys.version_info
    detail = f"{v[0]}.{v[1]}.{v[2]}"
    if tuple(v[:2]) < MIN_PYTHON:
        return "fail", detail, f"Velora needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer (install.sh and install-dev.sh download a private one for you)"
    return "ok", detail, ""


def parse_os_release(text: str) -> dict:
    out = {}
    for line in (text or "").splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def os_support(info: dict) -> dict:
    """{'name', 'status': supported|works|eol|untested, 'note'}"""
    ident, ver = (info.get("ID") or "").lower(), info.get("VERSION_ID") or ""
    name = info.get("PRETTY_NAME") or f"{ident} {ver}".strip() or "unknown system"
    table = {"ubuntu": UBUNTU, "debian": DEBIAN}.get(ident)
    if table and ver in table:
        status, note = table[ver]
        return {"name": name, "status": status, "note": note}
    if table:
        return {"name": name, "status": "untested", "note": f"Velora has not been checked on {name}. It needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ and PostgreSQL {MIN_POSTGRES}+; install.sh will tell you what it finds."}
    return {"name": name, "status": "untested", "note": "install.sh supports Ubuntu and Debian. On other systems install Python 3.10+ and PostgreSQL 13+ yourself, then `pip install velora`."}


def current_os() -> dict:
    try:
        with open("/etc/os-release") as f:
            return os_support(parse_os_release(f.read()))
    except OSError:
        return {"name": sys.platform, "status": "untested", "note": "Could not read /etc/os-release."}


def postgres_status(version_num: int) -> tuple[str, str, str]:
    """(status, detail, fix) for a server_version_num such as 160015."""
    major = version_num // 10000
    if major < MIN_POSTGRES:
        return "fail", f"{major}", (f"Velora needs PostgreSQL {MIN_POSTGRES} or newer. Ubuntu 18.04/20.04 ship older ones: install.sh adds the official repository ({PGDG_APT}) for you.")
    if major < RECOMMENDED_POSTGRES:
        return "warn", f"{major}", f"PostgreSQL {major} works but is near the end of its support: plan an upgrade to {RECOMMENDED_POSTGRES} or newer."
    return "ok", f"{major}", ""


def require_postgres(version_num: int) -> None:
    status, detail, fix = postgres_status(version_num)
    if status == "fail":
        raise UnsupportedPostgres(f"This PostgreSQL server is version {detail}, which is too old. {fix}")
