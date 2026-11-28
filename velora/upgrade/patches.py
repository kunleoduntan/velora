"""Data patches: one-off data migrations that ship with an app (or the framework) and run exactly once per database.

    <app>/patches.txt
        [pre_model_sync]        # before the schema is synced
        myapp.patches.v2.rename_status
        [post_model_sync]       # after (the default section) - e.g. backfill a new column
        myapp.patches.v2.fill_defaults

Each module defines `execute()`. A patch runs in its own transaction together with its log entry, so a failing patch changes nothing
and is simply retried on the next upgrade. Fresh installs record every existing patch as done without running it (there is no old data).
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

from sqlalchemy import insert, select

from .. import db
from ..db.system import patch_log
from ..document.document import now
from ..exceptions import PatchError

SECTIONS = ("pre_model_sync", "post_model_sync")
_PATH = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_]\w*)+$")


def _file(package: str) -> Path | None:
    try:
        mod = importlib.import_module(package)
    except ImportError:
        return None
    base = Path(mod.__file__).parent
    f = base / "patches.txt"
    return f if f.is_file() else None


def discover(package: str) -> dict[str, list[str]]:
    out = {s: [] for s in SECTIONS}
    f = _file(package)
    if not f:
        return out
    section, seen = "post_model_sync", set()
    for n, raw in enumerate(f.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            section = line.strip("[]").strip()
            if section not in SECTIONS:
                raise PatchError(f"{f}:{n}: unknown section {line!r} (use [pre_model_sync] or [post_model_sync])")
            continue
        if not _PATH.match(line):
            raise PatchError(f"{f}:{n}: {line!r} is not a dotted module path")
        if line in seen:
            raise PatchError(f"{f}:{n}: patch {line} is listed twice")
        seen.add(line)
        out[section].append(line)
    return out


def _packages(apps: list[str]) -> list[str]:
    return ["velora", *apps]                          # the framework's own patches always come first


def applied() -> set[str]:
    with db.transaction() as conn:
        from sqlalchemy import inspect
        if not inspect(conn).has_table("velora_patch_log"):
            return set()
        return set(conn.execute(select(patch_log.c.patch)).scalars())


def pending(apps: list[str], phase: str) -> list[str]:
    done = applied()
    return [p for pkg in _packages(apps) for p in discover(pkg)[phase] if p not in done]


def run(apps: list[str], phase: str, log=lambda m: None) -> list[str]:
    ran = []
    for path in pending(apps, phase):
        try:
            mod = importlib.import_module(path)
            fn = getattr(mod, "execute", None)
            if not callable(fn):
                raise PatchError(f"{path} must define execute()")
            with db.transaction() as conn:                   # patch + its log row commit together or not at all
                fn()
                conn.execute(insert(patch_log).values(patch=path, ran_on=now()))
        except PatchError:
            raise
        except Exception as e:  # noqa: BLE001 - any failure in app code becomes a clear, attributable error
            raise PatchError(f"Patch {path} failed: {type(e).__name__}: {e}", details={"patch": path}) from e
        ran.append(path)
        log(f"  patch {path}: done")
    return ran


def mark_applied(apps: list[str]) -> int:
    """Fresh database: everything that exists now counts as already applied."""
    done = applied()
    todo = [p for pkg in _packages(apps) for s in SECTIONS for p in discover(pkg)[s] if p not in done]
    with db.transaction() as conn:
        for p in todo:
            conn.execute(insert(patch_log).values(patch=p, ran_on=now()))
    return len(todo)
