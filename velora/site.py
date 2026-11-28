"""Site runtime: each site owns one database and one set of installed apps.

Everything that used to be process-global (engine, DocType registry, table cache) now lives on a
`Site`. The "current" site is a context variable, so one process can serve many sites safely:
the API selects it per request from the Host header, the CLI selects it with `--site`.
Library use (`velora.init()`) installs a single "default" site, so single-site code keeps working.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from sqlalchemy import MetaData, create_engine, inspect, select
from sqlalchemy.engine import URL, Engine

from .exceptions import MetaError
from .meta.registry import Registry

INSTALLED_TABLE = "velora_installed_app"


def _fix_sqlite_transactions(engine) -> None:
    """Python's sqlite3 driver decides for itself when a transaction starts and COMMITS silently before a SAVEPOINT, so a rollback after a savepoint could not undo earlier work
    (a dry-run import really saved its documents). Take control away from the driver, the way SQLAlchemy documents: BEGIN is emitted explicitly, so transactions, savepoints and
    rollbacks behave exactly as they do on PostgreSQL."""
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            # WAL: readers never wait for a writer and a writer never waits for readers. Without it, one background job or import that is
            # writing makes every page, link field and search wait (up to the busy timeout) and the Desk looks frozen on "Searching...".
            # FULL keeps every committed posting on disk even if the power fails.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=FULL")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")


class Site:
    def __init__(self, name: str, db_url: str, apps: list[str] | None = None, developer_mode: bool = False,
                 path: Path | None = None, config: dict | None = None, engine_kwargs: dict | None = None,
                 company: dict | None = None):
        self.name = name
        self.db_url = db_url
        self.developer_mode = developer_mode
        self.path = path
        self.config = config or {}
        self.engine_kwargs = engine_kwargs or {}
        self.company = company          # set when this site is a company database owned by a control plane
        self._fixed_apps = list(apps) if apps is not None else None   # None => read installed apps from the DB
        self._engine: Engine | None = None
        self.registry = Registry(self)
        self.waiting_for_apps: list[str] = []
        self.metadata = MetaData()
        self.table_cache: dict = {}
        self.metadata_extensions_cache: dict = {}

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            eng = create_engine(self.db_url, future=True, pool_pre_ping=True, **self.engine_kwargs)
            if eng.dialect.name == "sqlite":
                _fix_sqlite_transactions(eng)
            self._engine = eng
        return self._engine

    def installed_apps(self) -> list[str]:
        if self._fixed_apps is not None:
            return list(self._fixed_apps)
        from .db.system import installed_app
        with self.engine.connect() as c:
            if not inspect(c).has_table(INSTALLED_TABLE):
                return []
            return list(c.execute(select(installed_app.c.name).order_by(installed_app.c.installed_on, installed_app.c.name)).scalars())

    def load(self) -> "Site":
        """(Re)load DocType metadata for the installed apps."""
        self.reset_tables()
        self.waiting_for_apps = []
        installed = self.installed_apps()
        try:
            self.registry.load(installed)
        except MetaError:
            waiting = self._required_but_missing(installed)
            if not waiting:
                raise
            # An app update now needs apps this database does not have yet (`velora upgrade` installs them). Until then the
            # site loads empty, so the upgrade can run; the gate keeps requests out meanwhile.
            self.waiting_for_apps = waiting
            self.reset_tables()
            self.registry.load([])
            return self
        # Custom DocTypes are stored in this site's own database, so each company
        # sees only the objects created in its own workspace/database.
        from .db.system import setting
        with self.engine.connect() as conn:
            if inspect(conn).has_table("velora_setting"):
                definitions = conn.execute(select(setting.c.value).where(setting.c.key == "meta.company_doctypes")).scalar_one_or_none()
                self.registry.load_company_doctypes(definitions or [], strict=False)
        # Framework-owned company-local registries are provisioned before document
        # transactions begin; never perform DDL from inside a document lifecycle hook.
        from .scripts import ensure as ensure_scripts
        from .workflow_automation import ensure as ensure_workflow_automation
        ensure_scripts(self.engine)
        ensure_workflow_automation(self.engine)
        return self

    @staticmethod
    def _required_but_missing(installed: list[str]) -> list[str]:
        from . import apps as apps_mod
        out: list[str] = []
        for a in installed:
            for r in sorted(apps_mod._reachable(a)):
                if r not in installed and r not in out:
                    out.append(r)
        return out

    def reset_tables(self):
        self.table_cache.clear()
        self.metadata.clear()
        self.metadata_extensions_cache.clear()

    def dispose(self):
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def __repr__(self):
        return f"<Site {self.name}>"


def db_url_from_config(cfg: dict, site_dir: Path | None) -> str:
    if cfg.get("db_url"):
        return cfg["db_url"]
    if cfg.get("db_type", "sqlite") == "sqlite":
        return f"sqlite:///{(site_dir / cfg.get('db_name', 'site.db')).resolve()}"
    return URL.create("postgresql+psycopg", username=cfg["db_user"], password=cfg.get("db_password"),
                      host=cfg.get("db_host", "localhost"), port=int(cfg.get("db_port", 5432)),
                      database=cfg["db_name"]).render_as_string(hide_password=False)


def read_site_config(site_dir: Path) -> dict:
    return json.loads((site_dir / "site_config.json").read_text())


def site_from_dir(site_dir: Path) -> Site:
    cfg = read_site_config(site_dir)
    return Site(site_dir.name, db_url_from_config(cfg, site_dir), developer_mode=bool(cfg.get("developer_mode")),
                path=site_dir, config=cfg)


# ---- current site ---------------------------------------------------------------------------
_current: ContextVar[Site | None] = ContextVar("velora_site", default=None)
_default: Site | None = None
_cache: dict[str, Site] = {}
_lock = threading.Lock()


def current() -> Site:
    s = _current.get() or _default
    if s is None:
        raise RuntimeError("No site selected. Call velora.init(), or run inside `with use(site)` / a CLI --site command.")
    return s


def set_default(site: Site | None):
    global _default
    if _default is not None and _default is not site:
        _default.dispose()
    _default = site


@contextmanager
def use(site: Site):
    token = _current.set(site)
    try:
        yield site
    finally:
        _current.reset(token)


def load_site(site_dir: Path) -> Site:
    """Load (once) and cache a workspace site. Thread-safe: concurrent first requests share one load."""
    key = str(site_dir.resolve())
    with _lock:
        site = _cache.get(key)
        if site is None:
            site = site_from_dir(site_dir)
            site.load()
            _cache[key] = site
        return site


def unload_site(site_dir: Path):
    with _lock:
        s = _cache.pop(str(site_dir.resolve()), None)
    if s:
        s.dispose()


def unload_all():
    with _lock:
        sites = list(_cache.values())
        _cache.clear()
    for s in sites:
        s.dispose()
