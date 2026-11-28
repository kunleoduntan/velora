"""PostgreSQL connection budget.

Every company has its own database and therefore its own connection pool. Without a limit the worst case grows with the number of companies (the router could hold 64 pools of
up to 8 connections = 512) and a server with PostgreSQL's default max_connections = 100 ran out of slots. Here the worst case is computed and kept under a budget (default 48,
about half of a default server), every connection is labelled with `application_name`, and running out is reported as a readable message, not a traceback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {"connection_budget": 48, "control_pool_size": 2, "control_max_overflow": 3, "company_pool_size": 3, "company_max_overflow": 3,
            "pool_timeout": 10, "pool_recycle": 1800, "connect_timeout": 10}
LIMITS = {"connection_budget": (11, 5000), "control_pool_size": (1, 50), "control_max_overflow": (0, 50), "company_pool_size": (1, 50), "company_max_overflow": (0, 50),
          "pool_timeout": (1, 300), "pool_recycle": (30, 86400), "connect_timeout": (1, 120)}
EXHAUSTION_MESSAGE = ("PostgreSQL has no free connection slots. Something is holding them (run `velora pg status` to see who). "
                      "Lower `db_pool.connection_budget` in config/common.json, or raise max_connections in PostgreSQL, then try again.")


class PoolSettingError(ValueError):
    pass


def settings(workspace=None, overrides: dict | None = None) -> dict:
    """The defaults, then `db_pool` from config/common.json, then `overrides`; every value is range-checked."""
    out = dict(DEFAULTS)
    if workspace is not None:
        f = Path(workspace if isinstance(workspace, (str, Path)) else workspace.root) / "config" / "common.json"
        try:
            out.update((json.loads(f.read_text()) or {}).get("db_pool") or {})
        except (OSError, ValueError):
            pass
    out.update(overrides or {})
    for k, v in out.items():
        if k not in LIMITS:
            raise PoolSettingError(f"Unknown pool setting '{k}'")
        lo, hi = LIMITS[k]
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise PoolSettingError(f"db_pool.{k} must be a whole number from {lo} to {hi}, not {v!r}")
    if out["connection_budget"] < out["control_pool_size"] + out["control_max_overflow"] + out["company_pool_size"] + out["company_max_overflow"]:
        raise PoolSettingError("db_pool.connection_budget is too small for even one company")
    return out


def per_company(s: dict) -> int:
    return s["company_pool_size"] + s["company_max_overflow"]


def max_company_pools(s: dict) -> int:
    """How many company pools may be open at once so the worst case stays within the budget (at least 1)."""
    return max(1, (s["connection_budget"] - s["control_pool_size"] - s["control_max_overflow"]) // per_company(s))


def worst_case(s: dict, open_pools: int | None = None) -> int:
    n = max_company_pools(s) if open_pools is None else open_pools
    return s["control_pool_size"] + s["control_max_overflow"] + n * per_company(s)


def application_name(role: str, ident: str = "") -> str:
    return f"velora:{role}{':' + ident if ident else ''}:{os.getpid()}"[:63]


def control_kwargs(s: dict) -> dict:
    return {"pool_size": s["control_pool_size"], "max_overflow": s["control_max_overflow"], "pool_timeout": s["pool_timeout"], "pool_recycle": s["pool_recycle"],
            "connect_args": {"application_name": application_name("control"), "connect_timeout": s["connect_timeout"]}}


def company_kwargs(s: dict, company_id: str) -> dict:
    return {"pool_size": s["company_pool_size"], "max_overflow": s["company_max_overflow"], "pool_timeout": s["pool_timeout"], "pool_recycle": s["pool_recycle"],
            "connect_args": {"application_name": application_name("company", company_id), "connect_timeout": s["connect_timeout"]}}


def is_connection_exhaustion(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "remaining connection slots" in text or "too many clients" in text or "too many connections" in text
