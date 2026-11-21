"""`velora quickstart`: from `pip install velora` to a running, signed-in system in one command."""
from __future__ import annotations

import secrets
import string
import sys
import webbrowser
from pathlib import Path

from .controlplane import ControlPlane
from .workspace import Workspace, WorkspaceError


def generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(16))


def quickstart(path: str, *, email: str, password: str | None, company: str, sample: bool = True, db: str = "sqlite", db_kwargs: dict | None = None,
               log=print) -> dict:
    """Create a workspace, the control plane, one company (optionally with a sample app), and an administrator. Returns what the user needs."""
    from . import scaffold
    from .cli import _need_workspace  # noqa: F401  (kept for symmetry)
    if not email or "@" not in email:
        raise WorkspaceError("Give an administrator email, e.g. --email you@company.com")
    root = Path(path).expanduser()
    if (root / "platform" / "control_plane.json").exists():
        raise WorkspaceError(f"{root} is already set up. Start it with:  cd {path} && velora start")
    generated = password is None
    password = password or generate_password()
    ws = Workspace(root) if Workspace.is_workspace(root) else Workspace.create(root)
    from .lifecycle import BUILTIN_DEFAULT_APPS
    cfg = ws.common_config()
    ws.update_config(default_apps=cfg.get("default_apps", list(BUILTIN_DEFAULT_APPS)), auto_upgrade=cfg.get("auto_upgrade", True))      # notifications + search for every company; self-upgrading server
    log(f"1/5  Workspace ready at {ws.root}")
    apps: list[str] = []
    if sample:
        a = scaffold.new_app(ws.apps_dir, "starter", module="Starter", title="Starter")
        ws.register_app("starter")
        scaffold.new_doctype(a, "starter", "Contact", module="Starter")
        apps.append("starter")
        log("2/5  Created a sample app (starter) with a Contact DocType - edit it under apps/starter")
    else:
        log("2/5  Skipped the sample app")
    ws.activate()
    kw = db_kwargs or {}
    plane = ControlPlane.create(ws, db=db, admin_email=email, admin_password=password, **kw)
    log(f"3/5  Control plane created ({db})")
    tenant = plane.registry.create_tenant(f"{company} Group")
    co = plane.provisioning.provision_company(tenant["id"], company, apps=apps, db=db, **{k: v for k, v in kw.items() if k.startswith("db_") or k.startswith("root_")})
    log(f"4/5  Company {co['id']} ({company}) created with its own database")
    plane.identity.grant(email, co["id"], ["System Manager"])
    plane.dispose()
    log(f"5/5  Administrator {email} can work in {company}")
    from . import eventlog
    installed = list(dict.fromkeys([*ws.common_config().get("default_apps", []), *apps]))
    eventlog.record(ws, "install", "Velora is installed and ready", [
        f"Created your workspace at {ws.root}",
        "Set up the control plane (sign-in, companies and database routing)",
        f"Created the company {company} ({co['id']}) with its own {db} database",
        f"Installed these apps in it: {', '.join(installed) or 'none yet'}",
        f"Created the administrator {email}" + (" with a generated password" if generated else ""),
    ], company=co["id"])
    from . import layout
    layout.secure(ws)                                                 # databases, keys and settings are owner-only from the first minute
    return {"workspace": str(ws.root), "email": email, "password": password if generated else None, "company": co["id"], "generated_password": generated}


def open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - a headless machine has no browser; the URL is printed anyway
        pass


def is_interactive() -> bool:
    return sys.stdin.isatty()
