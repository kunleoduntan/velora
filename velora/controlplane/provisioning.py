"""Database Provisioning Engine: create a company's database, install its apps, record the outcome.

States (cp_company.status / provisioning_status):
  provisioning: creating_database → initializing → installing_apps → ready (status becomes `active`)
  on any failure: status `failed` with the error recorded, and whatever Velora created is cleaned up.
"""
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from sqlalchemy import delete

from .. import __version__, apps as apps_mod, dbadmin, pgadmin, provision, site as site_mod
from ..db import schema
from ..exceptions import ValidationError
from ..workspace import WorkspaceError
from . import models as m


class Provisioning:
    def __init__(self, plane):
        self.plane = plane

    def provision_company(self, tenant: str, name: str, *, code: str | None = None, apps=(), db: str = "sqlite",
                          db_host: str = "localhost", db_port: int = 5432, db_name: str | None = None, db_user: str | None = None,
                          db_password: str | None = None, root_user: str | None = None, root_password: str | None = None,
                          actor: str = "cli") -> dict:
        plane, reg = self.plane, self.plane.registry
        if db == "postgres":
            root_user, root_password, _ = pgadmin.resolve(plane.ws, root_user, root_password)     # the installer's administrator login, so nobody has to type it
        t = reg.get_tenant(tenant)
        if not t:
            raise ValidationError(f"No such tenant: {tenant}")
        if db not in ("sqlite", "postgres"):
            raise ValidationError("db must be 'sqlite' or 'postgres'")
        from ..apps import BUNDLED_APPS
        ws_apps = plane.ws.apps()
        apps = list(dict.fromkeys([*plane.ws.common_config().get("default_apps", []), *apps]))     # the built-in features every company should have (set by `velora quickstart`)     # the built-in features every company should have (set by `velora quickstart`)
        unknown = [a for a in apps if a not in ws_apps and a not in BUNDLED_APPS]
        if unknown:
            raise WorkspaceError(f"Not in this workspace: {', '.join(unknown)}")
        if db == "postgres" and not root_password and not (db_name and db_user and db_password):
            raise WorkspaceError("PostgreSQL needs --db-root-password (Velora creates the database) or --db-name/--db-user/--db-password (existing, empty)")

        row = reg.create_company_row(t["id"], name, code, db_engine=db, provisioning_status="creating_database")
        cid = row["id"]
        created: dict = {"pg": None, "file": None, "secret": None}
        try:
            fields: dict = {}
            if db == "sqlite":
                f = plane.platform_dir / "companies" / f"{cid}.db"
                f.parent.mkdir(parents=True, exist_ok=True)
                fields.update(db_name=f.relative_to(plane.platform_dir).as_posix())       # relative: the workspace can be moved or restored anywhere
                created["file"] = f
            else:
                fields.update(db_host=db_host, db_port=int(db_port))
                if root_password:                                           # Velora creates a role + database
                    ident = re.sub(r"[^a-z0-9]+", "_", f"velora_{row['code']}")[:50].strip("_") + "_" + secrets.token_hex(2)
                    pw = db_password or secrets.token_urlsafe(24)
                    dbadmin.provision_pg(db_host, db_port, root_user, root_password, db_name or ident, db_user or ident, pw)
                    created["pg"] = (db_host, db_port, root_user, root_password, db_name or ident, db_user or ident)
                    fields.update(db_name=db_name or ident, db_user=db_user or ident, provisioned_db=True)
                else:                                                       # existing database (managed hosting)
                    pw = db_password
                    fields.update(db_name=db_name, db_user=db_user)
                fields["secret_ref"] = created["secret"] = plane.secrets.put(pw)          # the password never touches the registry
            reg.update_company(cid, **fields, provisioning_status="initializing")
            co = reg.get_company(cid)
            if db == "postgres" and not root_password:
                dbadmin.check_connect(plane.router.db_url(co))
                dbadmin.check_empty_database(plane.router.db_url(co))

            site = plane.router.site_for(co)
            with site_mod.use(site):
                schema.ensure_system_tables()
                provision._stamp_fresh()
            reg.update_company(cid, provisioning_status="installing_apps")
            plane.ws.activate()
            from .. import lifecycle
            with site_mod.use(site):
                have = set(site.installed_apps())
            for app in apps:
                # dependencies first; apps that need each other (VeloraERP and ProjectOne) go in together, as `velora install-app` does
                for a in lifecycle._install_order(app):
                    if a in have:
                        continue
                    group = [g for g in apps_mod.cycle_of(a) if g != a and g not in have]
                    apps_mod.install_app(plane.ws, site, a, together=group)
                    have |= {a, *group}
            reg.update_company(cid, status="active", provisioning_status="ready", provisioning_error=None, schema_version=__version__)
        except BaseException as e:
            plane.router.forget(cid)
            reg.update_company(cid, status="failed", provisioning_error=str(e)[:1000])
            self._cleanup(created)
            plane.audit("company.provision_failed", actor=actor, subject=cid, detail={"error": str(e)[:300]})
            raise
        plane.audit("company.provision", actor=actor, subject=cid, detail={"apps": list(apps), "db": db})
        from .. import layout
        layout.secure(plane.ws)                                           # the new company's database file is owner-only from the moment it exists
        return reg.get_company(cid)

    def _cleanup(self, created: dict):
        try:
            if created["pg"]:
                dbadmin.drop_pg(*created["pg"])
            if created["file"] and Path(created["file"]).exists():
                os.remove(created["file"])
            if created["secret"]:
                self.plane.secrets.delete(created["secret"])
        except Exception:  # noqa: BLE001 - cleanup is best effort; the failure is already recorded
            pass

    def drop_company(self, company_id: str, *, root_user: str | None = None, root_password: str | None = None, actor: str = "cli") -> str:
        plane = self.plane
        root_user, root_password, _ = pgadmin.resolve(plane.ws, root_user, root_password)
        co = plane.registry.get_company(company_id)
        if not co:
            raise ValidationError(f"No such company: {company_id}")
        note = "database left untouched"
        if co["db_engine"] == "postgres" and co["provisioned_db"]:
            if not root_password:
                raise WorkspaceError("This company's PostgreSQL database was created by Velora; set up the administrator login with `velora pg admin set`, or pass --db-root-password")
            plane.router.forget(co["id"])
            dbadmin.drop_pg(co["db_host"], co["db_port"], root_user, root_password, co["db_name"], co["db_user"])
            note = "database and role dropped"
        elif co["db_engine"] == "postgres":
            note = "the PostgreSQL database was NOT dropped (Velora did not create it)"
        elif co["db_engine"] == "sqlite" and co["db_name"] and plane.sqlite_path(co).exists():
            plane.router.forget(co["id"])
            os.remove(plane.sqlite_path(co))
            note = "database file deleted"
        if co["secret_ref"]:
            plane.secrets.delete(co["secret_ref"])
        with plane.engine.begin() as c:
            c.execute(delete(m.user_company).where(m.user_company.c.company_id == co["id"]))
            c.execute(m.session.update().where(m.session.c.active_company_id == co["id"]).values(active_company_id=None))
            c.execute(delete(m.company).where(m.company.c.id == co["id"]))
        plane.audit("company.drop", actor=actor, subject=co["id"], detail={"note": note})
        return note
