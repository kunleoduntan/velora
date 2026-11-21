"""Database Router: company → (cached) Site with its own connection pool.

Request-scoped by construction: nothing here changes a global "active database". Callers get a `Site` object and
bind it to the *current request* with `site.use(site)` (a context variable), so two users working in two different
companies at the same moment never see each other's connections.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from sqlalchemy.engine import URL

from .. import dbpool
from ..site import Site
from ..workspace import WorkspaceError


class DatabaseRouter:
    def __init__(self, plane, max_pools: int | None = None, pool_size: int | None = None, max_overflow: int | None = None, refresh_seconds: float = 30.0):
        self.plane = plane
        cfg = getattr(plane, "db_settings", None) or dbpool.settings()
        self.max_pools = max_pools or dbpool.max_company_pools(cfg)               # derived from the connection budget
        self.pool_size = pool_size or cfg["company_pool_size"]
        self.max_overflow = cfg["company_max_overflow"] if max_overflow is None else max_overflow
        self.refresh_seconds = refresh_seconds
        self._sites: "OrderedDict[str, tuple[Site, tuple, float]]" = OrderedDict()
        self._lock = threading.RLock()

    # ---- connection settings -------------------------------------------------------------------
    def _fingerprint(self, co: dict) -> tuple:
        return (co["db_engine"], co["db_host"], co["db_port"], co["db_name"], co["db_user"], co["secret_ref"])

    def db_url(self, co: dict) -> str:
        if co["db_engine"] == "sqlite":
            return f"sqlite:///{self.plane.sqlite_path(co)}"
        password = self.plane.secrets.get(co["secret_ref"]) if co["secret_ref"] else None
        return URL.create("postgresql+psycopg", username=co["db_user"], password=password, host=co["db_host"] or "localhost",
                          port=int(co["db_port"] or 5432), database=co["db_name"]).render_as_string(hide_password=False)

    def db_config(self, co: dict) -> dict:
        """A site_config-style dict (used by backup tooling). Contains the decrypted password - never log it."""
        if co["db_engine"] == "sqlite":
            return {"db_type": "sqlite"}
        return {"db_type": "postgres", "db_host": co["db_host"], "db_port": co["db_port"], "db_name": co["db_name"], "db_user": co["db_user"],
                "db_password": self.plane.secrets.get(co["secret_ref"])}

    # ---- routing --------------------------------------------------------------------------------
    def site_for(self, co: dict) -> Site:
        if co["status"] not in ("active", "provisioning"):
            raise WorkspaceError(f"Company {co['id']} is {co['status']}")
        with self._lock:
            hit = self._sites.get(co["id"])
            fp = self._fingerprint(co)
            if hit and hit[1] == fp:
                site, _, checked = hit
                if time.monotonic() - checked > self.refresh_seconds:        # pick up `install-app` run by another process
                    if site.installed_apps() != list(site.registry._apps):
                        site.load()
                    self._sites[co["id"]] = (site, fp, time.monotonic())
                self._sites.move_to_end(co["id"])
                return site
            if hit:
                hit[0].dispose()                                              # connection settings changed: rebuild
            site = Site(co["id"], self.db_url(co), engine_kwargs=self._engine_kwargs(co),
                        company={"id": co["id"], "name": co["name"], "tenant_id": co["tenant_id"]})
            site.load()
            self._sites[co["id"]] = (site, fp, time.monotonic())
            while len(self._sites) > self.max_pools:                          # evict the least recently used pool
                _, (old, _, _) = self._sites.popitem(last=False)
                old.dispose()
            return site

    def _engine_kwargs(self, co: dict) -> dict:
        if co["db_engine"] != "postgres":
            return {}
        kw = dbpool.company_kwargs(self.plane.db_settings, co["id"])
        kw["pool_size"], kw["max_overflow"] = self.pool_size, self.max_overflow
        return kw

    def forget(self, company_id: str):
        with self._lock:
            hit = self._sites.pop(company_id, None)
        if hit:
            hit[0].dispose()

    def active_pools(self) -> list[str]:
        with self._lock:
            return list(self._sites)

    def dispose_all(self):
        with self._lock:
            sites, self._sites = list(self._sites.values()), OrderedDict()
        for s, _, _ in sites:
            s.dispose()
