"""The Velora Control Plane: central identity, tenant/company registry and database routing.

    platform/control_plane.json   connection settings for the control-plane database (mode 600)
    platform/master.key           encrypts company database credentials (mode 600; or use VELORA_MASTER_KEY)
    platform/companies/           SQLite company databases (development only)
"""
from __future__ import annotations

import json
import os
import secrets as _secrets
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from .. import __version__, dbadmin, dbpool, provision, site as site_mod
from ..db import schema
from ..document.document import now
from ..workspace import Workspace, WorkspaceError
from .directory import PlaneDirectory
from . import models as m
from .identity import Identity
from .provisioning import Provisioning
from .registry import Registry
from .router import DatabaseRouter
from .secrets import SecretStore, generate_master_key, load_master_key


class ControlPlane:
    def __init__(self, ws: Workspace, cfg: dict, engine, secrets: SecretStore):
        self.ws, self.cfg, self.engine, self.secrets = ws, cfg, engine, secrets
        self.platform_dir = ws.root / "platform"
        self.registry = Registry(self)
        self.identity = Identity(self)
        self.db_settings = dbpool.settings(ws)
        self.router = DatabaseRouter(self)
        self.provisioning = Provisioning(self)

    # ---- lifecycle ------------------------------------------------------------------------------
    @staticmethod
    def exists(ws: Workspace) -> bool:
        return (ws.root / "platform" / "control_plane.json").exists()

    @classmethod
    def open(cls, ws: Workspace) -> "ControlPlane":
        pdir = ws.root / "platform"
        cfg_file = pdir / "control_plane.json"
        if not cfg_file.exists():
            raise WorkspaceError("No control plane here. Run `velora platform init` first.")
        cfg = json.loads(cfg_file.read_text())
        kw = dbpool.control_kwargs(dbpool.settings(ws)) if cfg.get("db_type") == "postgres" else {}
        engine = create_engine(site_mod.db_url_from_config(cfg, pdir), future=True, pool_pre_ping=True, **kw)
        return cls(ws, cfg, engine, SecretStore(load_master_key(pdir), engine))

    @classmethod
    def create(cls, ws: Workspace, *, db: str = "sqlite", db_host: str = "localhost", db_port: int = 5432, db_name: str | None = None,
               db_user: str | None = None, db_password: str | None = None, root_user: str = "postgres", root_password: str | None = None,
               admin_email: str | None = None, admin_password: str | None = None, admin_name: str = "Platform Administrator") -> "ControlPlane":
        pdir = ws.root / "platform"
        if (pdir / "control_plane.json").exists():
            raise WorkspaceError("This workspace already has a control plane")
        if db not in ("sqlite", "postgres"):
            raise WorkspaceError("--db must be 'sqlite' or 'postgres'")
        pdir.mkdir(exist_ok=True)
        cfg: dict = {"db_type": db, "created_on": now().isoformat(timespec="seconds"), "version": __version__}
        provisioned = False
        try:
            if db == "sqlite":
                cfg["db_name"] = "control.db"
            else:
                cfg.update(db_host=db_host, db_port=int(db_port))
                if root_password:
                    ident = "velora_cp_" + _secrets.token_hex(6)           # unique per workspace: several can share one PostgreSQL server
                    cfg.update(db_name=db_name or ident, db_user=db_user or ident, db_password=db_password or _secrets.token_urlsafe(24), provisioned_db=True)
                    dbadmin.provision_pg(db_host, db_port, root_user, root_password, cfg["db_name"], cfg["db_user"], cfg["db_password"])
                    provisioned = True
                elif db_name and db_user and db_password:
                    cfg.update(db_name=db_name, db_user=db_user, db_password=db_password)
                    dbadmin.check_connect(site_mod.db_url_from_config(cfg, pdir))
                else:
                    raise WorkspaceError("PostgreSQL needs --db-root-password or --db-name/--db-user/--db-password")
            cfg_file = pdir / "control_plane.json"
            cfg_file.write_text(json.dumps(cfg, indent=2) + "\n")
            os.chmod(cfg_file, 0o600)
            if not os.environ.get("VELORA_MASTER_KEY"):
                key_file = pdir / "master.key"
                key_file.write_bytes(generate_master_key() + b"\n")
                os.chmod(key_file, 0o600)
            plane = cls.open(ws)
            m.cp_metadata.create_all(plane.engine)
            plane._stamp()
            if admin_email:
                plane.identity.create_user(admin_email, admin_name, admin_password or "", is_platform_admin=True)
            plane.audit("platform.init", actor="cli", detail={"db": db})
            return plane
        except BaseException:
            for f in ("control_plane.json", "master.key", "control.db"):
                (pdir / f).unlink(missing_ok=True)
            if provisioned:
                dbadmin.drop_pg(db_host, db_port, root_user, root_password, cfg["db_name"], cfg["db_user"])
            raise

    # ---- control-plane schema versioning / upgrade -------------------------------------------------
    def schema_version(self) -> str | None:
        with self.engine.connect() as c:
            from sqlalchemy import inspect
            if not inspect(c).has_table("cp_meta"):
                return None
            r = c.execute(select(m.meta.c.value).where(m.meta.c.key == "schema_version")).first()
        return r[0] if r else None

    def _stamp(self):
        from ..upgrade.versions import code_version
        with self.engine.begin() as c:
            if c.execute(update(m.meta).where(m.meta.c.key == "schema_version").values(value=code_version())).rowcount == 0:
                c.execute(insert(m.meta).values(key="schema_version", value=code_version()))
        self._gate = None

    def pending_upgrade(self) -> tuple[str, str | None]:
        """Cached for a few seconds: ('ok'|'upgrade_pending'|'downgrade', recorded_version)."""
        import time
        from ..upgrade.state import gate_state
        g = getattr(self, "_gate", None)
        if g and time.monotonic() - g[0] < 5:
            return g[1]
        state = gate_state(self.schema_version())
        self._gate = (time.monotonic(), state)
        return state

    def migrate(self, dry_run: bool = False) -> list[str]:
        """Bring the control plane's own tables up to date (new tables, new columns). Additive and safe."""
        from ..db import schema
        plan: list[str] = []
        with self.engine.begin() as conn:
            for t in m.cp_metadata.sorted_tables:
                schema._sync_table(conn, t, plan, dry_run)
        if not dry_run:
            self._stamp()
            n = self.normalize_company_paths()
            if n:
                plan.append(f"make {n} company database path(s) relative to the workspace")
        return plan

    def dispose(self):
        self.router.dispose_all()
        self.engine.dispose()

    # ---- audit ------------------------------------------------------------------------------------
    def audit(self, event: str, actor: str | None = None, subject: str | None = None, detail: dict | None = None):
        try:
            with self.engine.begin() as c:
                c.execute(insert(m.audit).values(id=_secrets.token_hex(12), ts=now(), actor=actor, event=event, subject=subject, detail=detail))
        except SQLAlchemyError:
            pass        # auditing must never take the platform down

    # ---- operations across companies ------------------------------------------------------------------
    def migrate_company(self, company: dict, dry_run: bool = False) -> list[str]:
        site = self.router.site_for(company)
        with site_mod.use(site):
            schema.ensure_system_tables()
            site.load()
            plan = schema.migrate(dry_run=dry_run)
        if not dry_run:
            self.registry.update_company(company["id"], schema_version=__version__)
        return plan

    def migrate_all(self, dry_run: bool = False) -> list[dict]:
        """Roll the framework upgrade across every active company, one at a time; a failure never blocks the others."""
        out = []
        for co in self.registry.list_companies():
            if co["status"] != "active":
                out.append({"company": co["id"], "skipped": co["status"]})
                continue
            try:
                out.append({"company": co["id"], "plan": self.migrate_company(co, dry_run)})
            except Exception as e:  # noqa: BLE001
                out.append({"company": co["id"], "error": str(e).splitlines()[0][:300]})
        return out

    def sqlite_path(self, company: dict) -> Path:
        """Where a SQLite company's database file is, RIGHT NOW. New companies store a path relative to the platform folder (`companies/COMP-001.db`), so a workspace can be moved,
        renamed, copied to a new server or restored from a backup and still open its own data. An older absolute path that no longer exists is healed to the same file
        inside this workspace (it was recorded where the workspace USED to be)."""
        raw = Path(company["db_name"])
        if not raw.is_absolute():
            return (self.platform_dir / raw).resolve()
        if raw.exists():
            return raw
        here = self.platform_dir / "companies" / raw.name
        return here.resolve() if here.exists() else raw

    def normalize_company_paths(self) -> int:
        """Rewrite absolute SQLite paths that lie inside this workspace as relative ones (so the workspace is relocatable). Returns how many were changed."""
        from sqlalchemy import update
        changed = 0
        for co in self.registry.list_companies():
            if co["db_engine"] != "sqlite" or not co["db_name"] or not Path(co["db_name"]).is_absolute():
                continue
            found = self.sqlite_path(co)
            try:
                relative = found.relative_to(self.platform_dir.resolve())
            except ValueError:
                continue                                                          # a database kept outside the workspace on purpose: leave it alone
            if found.exists():
                with self.engine.begin() as c:
                    c.execute(update(m.company).where(m.company.c.id == co["id"]).values(db_name=relative.as_posix()))
                self.router.forget(co["id"])
                changed += 1
        return changed

    def backup_company(self, company: dict) -> Path:
        cfg = self.router.db_config(company)
        sqlite_file = self.sqlite_path(company) if company["db_engine"] == "sqlite" else None
        return provision.backup_database(cfg, sqlite_file, self.platform_dir / "backups" / company["id"], company["code"])

    @contextmanager
    def company_scope(self, company_id: str, user_email: str = "Administrator", roles=("System Manager",)):
        """Run trusted code (scripts, jobs, tests) inside a company: binds its database, company info and a session."""
        from ..company import CompanyInfo, company_context
        from ..permissions import Session, session_as
        co = self.registry.get_company(company_id)
        if co is None:
            raise WorkspaceError(f"No such company: {company_id}")
        site = self.router.site_for(co)
        tenant = self.registry.get_tenant(co["tenant_id"]) or {}
        with site_mod.use(site), company_context(CompanyInfo(co["id"], co["name"], co["tenant_id"], tenant.get("name", ""), PlaneDirectory(self, co["id"]))), \
                session_as(Session(user_email, frozenset(roles))):
            yield site
