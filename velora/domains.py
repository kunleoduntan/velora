"""Give a company its own web address:   velora domain add erp.acme.com COMP-001

One command: checks the name, checks that DNS already points somewhere, registers the address for that company, and - on a server installed with install.sh - has a small
root helper write the web-server (nginx) site and get the HTTPS certificate. If any step fails the registration is undone, so nothing is left half-done.
On that address people see only that company (it is 'locked' unless you say otherwise)."""
from __future__ import annotations

import shlex
import socket
import subprocess

from . import eventlog
from .controlplane import ControlPlane
from .controlplane.registry import normalize_domain
from .exceptions import ValidationError
from .workspace import Workspace, WorkspaceError


def resolve(domain: str) -> list[str]:
    """The IP addresses a name points to ([] if it does not resolve yet)."""
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(domain, None)})
    except socket.gaierror:
        return []


def nginx_snippet(domain: str, port: int = 8000) -> str:
    return f"""server {{
    listen 80;
    server_name {domain};
    client_max_body_size 50m;
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;                       # Velora decides the company from this
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    location /api/events {{                                # live notifications: never buffer the stream
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 1h;
    }}
}}"""


def _helper_cmd(ws: Workspace, action: str, domain: str, tls: bool) -> list[str] | None:
    cfg = ws.common_config().get("domain", {})
    if not cfg.get("helper"):
        return None
    cmd = [*shlex.split(cfg["helper"]), action, domain, "--port", str(cfg.get("port", 8000))]
    if action == "add":
        if not tls:
            cmd.append("--no-tls")
        elif cfg.get("email"):
            cmd += ["--email", cfg["email"]]
    return cmd


def run_helper(ws: Workspace, action: str, domain: str, tls: bool, runner=subprocess.run) -> dict:
    cmd = _helper_cmd(ws, action, domain, tls)
    if cmd is None:
        return {"ran": False}
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ran": True, "ok": False, "output": str(e)}
    return {"ran": True, "ok": r.returncode == 0, "code": r.returncode, "output": ((r.stdout or "") + (r.stderr or "")).strip()[-600:]}


def _pick_company(plane, company: str | None) -> dict:
    if company:
        co = plane.registry.get_company(company)
        if co is None:
            raise WorkspaceError(f"No such company: {company}. See `velora company list`.")
        return co
    cos = plane.registry.list_companies()
    if len(cos) == 1:
        return cos[0]
    raise WorkspaceError("Which company is this address for? Add its id: velora domain add erp.acme.com COMP-001")


def add(ws: Workspace, domain: str, company: str | None = None, *, primary: bool = False, locked: bool = True, tls: bool | None = None,
        dry_run: bool = False, log=print, resolver=None, runner=subprocess.run) -> dict:
    try:
        d = normalize_domain(domain)
    except ValidationError as e:
        raise WorkspaceError(str(e)) from None
    plane = ControlPlane.open(ws)
    try:
        co = _pick_company(plane, company)
        if plane.registry.get_domain(d):
            have = plane.registry.company_for_domain(d)
            raise WorkspaceError(f"{d} is already registered" + (f" for {have['id']} {have['name']}" if have else "") + ". Remove it first (velora domain remove) to change it.")
        helper = _helper_cmd(ws, "add", d, True) is not None
        want_tls = helper if tls is None else tls
        ips = (resolver or resolve)(d)
        if want_tls and not ips:
            raise WorkspaceError(f"{d} does not exist in DNS yet, so an HTTPS certificate cannot be issued. Create an A record pointing {d} to this server, wait a few minutes, "
                                 f"then run the same command again. (Add --no-tls to register it now without HTTPS.) Nothing was changed.")
        log(f"{d} -> {co['id']} {co['name']}" + (f"   DNS: {', '.join(ips)}" if ips else "   DNS: not resolving yet"))
        if dry_run:
            log("Dry run: nothing was changed." + ("" if helper else "\nOn this server the web-server part is manual; this is the nginx site you would need:\n" + nginx_snippet(d, ws.common_config().get("domain", {}).get("port", 8000))))
            return {"domain": d, "company": co["id"], "dry_run": True}
        plane.registry.add_domain(d, co["id"], primary=primary, locked=locked, tls=False)
        res = run_helper(ws, "add", d, want_tls, runner)
        steps = [{"text": f"Registered {d} for {co['name']} ({co['id']})" + (" - people on this address see only this company" if locked else ""), "ok": True}]
        if res.get("ran") and not res.get("ok"):
            plane.registry.remove_domain(d)                                    # all or nothing
            log(f"The web server could not be set up ({res.get('output', '')}). The address was NOT registered.")
            eventlog.record(ws, "domain", f"Could not add {d}", [{"text": f"Web-server setup failed: {res.get('output', '')[:200]}", "ok": False}], ok=False, domain=d)
            raise WorkspaceError(f"Could not add {d}: {res.get('output', 'the web-server helper failed')}")
        if res.get("ran"):
            steps.append({"text": "Configured the web server (nginx) to serve it", "ok": True})
            if want_tls:
                plane.registry.set_domain_tls(d, True)
                steps.append({"text": "Obtained an HTTPS certificate (it renews automatically)", "ok": True})
        else:
            steps.append({"text": "Registered only: this server has no web-server helper, so add the nginx site yourself (see below)", "ok": True})
            log("This server has no web-server helper (it was not installed with install.sh). Add this nginx site, then HTTPS with certbot:\n" + nginx_snippet(d, ws.common_config().get("domain", {}).get("port", 8000)))
        eventlog.record(ws, "domain", f"Added the address {d}", steps, ok=True, domain=d, company=co["id"])
        log(f"Done: https://{d}" if want_tls and res.get("ran") else f"Done: {d} now opens {co['name']}.")
        return {"domain": d, "company": co["id"], "tls": bool(want_tls and res.get("ran")), "helper": bool(res.get("ran"))}
    finally:
        plane.dispose()


def remove(ws: Workspace, domain: str, log=print, runner=subprocess.run) -> dict:
    d = (domain or "").strip().lower()
    plane = ControlPlane.open(ws)
    try:
        row = plane.registry.get_domain(d)
        if row is None:
            raise WorkspaceError(f"{d} is not registered. See `velora domain list`.")
        res = run_helper(ws, "remove", d, False, runner)
        plane.registry.remove_domain(d)
        if res.get("ran") and not res.get("ok"):
            log(f"Removed the registration, but the web-server site could not be removed: {res.get('output', '')}")
        eventlog.record(ws, "domain", f"Removed the address {d}", [{"text": f"{d} no longer opens {row['company_id']}", "ok": True}], domain=d)
        log(f"Removed {d}.")
        return {"domain": d, "helper": res}
    finally:
        plane.dispose()


def listing(ws: Workspace) -> list[dict]:
    plane = ControlPlane.open(ws)
    try:
        names = {c["id"]: c["name"] for c in plane.registry.list_companies()}
        return [{**r, "company_name": names.get(r["company_id"], "?")} for r in plane.registry.list_domains()]
    finally:
        plane.dispose()
