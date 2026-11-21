"""Authentication, company selection and per-request database routing (platform mode).

Every request: authenticate (cookie or Bearer) → work out the company (X-Velora-Company header, else the session's
default, else the user's only company) → verify the user may enter it → bind THAT company's database, company info and
the user's roles *in that company* to this request only (context variables, never a global "active database").

Cookie sessions are HttpOnly + SameSite=Lax, and state-changing requests must also carry `X-Velora-Request: 1`
(a header a cross-site form cannot set), which blocks CSRF. Bearer-token clients are not exposed to CSRF and skip it.
"""
from __future__ import annotations

from contextlib import contextmanager
import os

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse

from .. import site as site_mod
from ..company import CompanyInfo, company_context
from ..controlplane.identity import SESSION_IDLE
from ..controlplane.directory import PlaneDirectory
from ..exceptions import AuthenticationRequired, PermissionDenied, ServiceUnavailable, UpgradePending, ValidationError
from ..permissions import Session, session_as
from ..tenant_security import resolve_tenant_company

COOKIE = "velora_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _token(request: Request) -> tuple[str | None, str]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None, "bearer"
    c = request.cookies.get(COOKIE)
    return (c, "cookie") if c else (None, "")


def _check_csrf(request: Request, source: str):
    if source == "cookie" and request.method not in SAFE_METHODS and request.headers.get("x-velora-request") != "1":
        raise PermissionDenied("Missing X-Velora-Request header")


def _https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"


def _bound(plane, request: Request):
    """The company this web address belongs to (acme-erp.example.com -> COMP-001), if it is registered."""
    return plane.registry.company_for_domain(request.headers.get("host"))


def _wanted_company(plane, request: Request) -> str | None:
    """Which company this request is for. On a company's own address that is the company itself: an address that is locked refuses any other company."""
    asked = request.headers.get("x-velora-company") or None
    b = _bound(plane, request)
    if b is None:
        return asked
    if asked and b["locked"] and asked not in (b["id"], b["name"]):
        raise PermissionDenied(f"This address is for {b['name']} only. Use your own company's address to reach {asked}.")
    return asked or b["id"]


def make_scope(plane):
    @contextmanager
    def scope(request: Request):
        token, source = _token(request)
        _check_csrf(request, source)
        # Company API credentials are scoped to exactly one company database. They
        # require an explicit company header and cannot use the user's company switcher.
        if token and token.startswith("vla_"):
            company_id = request.headers.get("x-velora-company")
            if not company_id:
                raise PermissionDenied("API-key requests must include X-Velora-Company")
            company = plane.registry.get_company(company_id)
            bound = _bound(plane, request)
            if not company or company.get("status", "active") != "active":
                raise PermissionDenied("The requested company is unavailable to this API credential")
            if bound is not None and bound["locked"] and bound["id"] != company["id"]:
                raise PermissionDenied("This address is restricted to its registered company")
            try:
                site = plane.router.site_for(company)
            except Exception:  # noqa: BLE001
                raise ServiceUnavailable("The company database is unavailable. Try again shortly.") from None
            from ..upgrade.state import check_site, gate_message
            gate, recorded = check_site(site)
            if gate != "ok":
                raise UpgradePending(gate_message(gate, recorded))
            with site_mod.use(site):
                from ..integration_engine import authenticate_api_key
                if request.url.path.endswith(("/submit", "/cancel")):
                    required_scope = "submit"
                elif "/report" in request.url.path:
                    required_scope = "reports"
                else:
                    required_scope = "read" if request.method in SAFE_METHODS else "write"
                credential = authenticate_api_key(token, required_scope=required_scope)
            if not credential:
                raise AuthenticationRequired("Invalid or expired company API credential")
            tenant = plane.registry.get_tenant(company["tenant_id"]) or {}
            info = CompanyInfo(company["id"], company["name"], company["tenant_id"], tenant.get("name", ""), PlaneDirectory(plane, company["id"]))
            roles = {"API Key"} | {f"API:{x}" for x in credential["scopes"]}
            with site_mod.use(site), company_context(info), session_as(Session("api:" + credential["id"], frozenset(roles))):
                yield
            return

        auth = plane.identity.resolve(token)
        tenant_ctx = resolve_tenant_company(plane, auth, _wanted_company(plane, request))
        company = plane.registry.get_company(tenant_ctx.company_id)
        roles = list(tenant_ctx.roles)
        try:
            site = plane.router.site_for(company)
        except Exception as e:  # noqa: BLE001 - unreachable database, bad credentials, missing secret ...
            plane.audit("company.unavailable", actor=auth.email, subject=company["id"], detail={"error": str(e).splitlines()[0][:200]})
            raise ServiceUnavailable("The company database is unavailable. Try again shortly.") from None
        from ..upgrade.state import check_site, gate_message
        gate, recorded = check_site(site)
        if gate != "ok":                                    # new code must never run against an un-upgraded database
            raise UpgradePending(gate_message(gate, recorded))
        info = CompanyInfo(tenant_ctx.company_id, tenant_ctx.company_name, tenant_ctx.tenant_id, tenant_ctx.tenant_name, PlaneDirectory(plane, tenant_ctx.company_id))
        with site_mod.use(site), company_context(info), session_as(Session(auth.email, frozenset(roles))):
            yield
    return scope


def install_auth_routes(app: FastAPI, plane):
    def profile(auth, request) -> dict:
        companies = plane.identity.companies_for(auth.user_id)
        b = _bound(plane, request)
        if b is not None and b["locked"]:
            companies = [c for c in companies if c["id"] == b["id"]]            # on a company's own address you only see that company
        active = None
        try:
            co, _ = plane.identity.authorize(auth, _wanted_company(plane, request))
            active = co["id"]
        except Exception:  # noqa: BLE001 - no usable company yet: the Desk shows the company picker
            pass
        return {"user": {"email": auth.email, "full_name": auth.full_name, "is_platform_admin": auth.is_platform_admin},
                "companies": [{"id": c["id"], "name": c["name"], "tenant": c["tenant_name"], "status": c["status"], "roles": c["roles"]} for c in companies],
                "active_company": active, "default_company": plane.identity.default_company(auth.user_id)}

    @app.get("/api/auth/config")
    def auth_config():
        return {"data": {"mode": "password", "company_header": "X-Velora-Company"}}

    @app.get("/api/domain")
    def this_domain(request: Request):
        """Public: which company does the address in the browser belong to? (so the sign-in screen can say 'Sign in to Acme')"""
        b = _bound(plane, request)
        return {"data": {"domain": b["domain"], "company": {"id": b["id"], "name": b["name"]}, "locked": b["locked"]} if b else {"domain": None, "company": None, "locked": False}}

    @app.get("/api/auth/login-branding")
    def login_branding(request: Request):
        """Public, read-only company branding for the sign-in screen on a registered company domain."""
        bound = _bound(plane, request)
        fallback_name = os.environ.get("VELORA_LOGIN_BRAND_NAME", "Velora").strip()[:60] or "Velora"
        fallback_tagline = os.environ.get("VELORA_LOGIN_TAGLINE", "Enterprise operations, in control.").strip()[:120]
        fallback_logo = os.environ.get("VELORA_LOGIN_LOGO_URL", "").strip()[:500]
        if not (fallback_logo.startswith("/") and not fallback_logo.startswith("//") or fallback_logo.startswith("https://")):
            fallback_logo = ""
        fallback = {"app_name": (bound["name"] if bound else fallback_name),
                    "tagline": fallback_tagline, "logo_url": fallback_logo}
        if bound is None:
            return {"data": fallback}
        company = plane.registry.get_company(bound["id"])
        if not company or company.get("status", "active") != "active":
            return {"data": fallback}
        try:
            site = plane.router.site_for(company)
            tenant = plane.registry.get_tenant(company.get("tenant_id", "")) or {}
            info = CompanyInfo(company["id"], company["name"], company.get("tenant_id", ""),
                               tenant.get("name", ""), PlaneDirectory(plane, company["id"]))
            from ..settings import get_setting
            with site_mod.use(site), company_context(info):
                cfg = get_setting("application.branding", {}) or {}
        except Exception:  # noqa: BLE001 - sign-in must remain available if a company DB is offline
            return {"data": fallback}
        app_name = cfg.get("app_name") if isinstance(cfg.get("app_name"), str) else ""
        tagline = cfg.get("tagline") if isinstance(cfg.get("tagline"), str) else ""
        logo_url = cfg.get("logo_url") if isinstance(cfg.get("logo_url"), str) else ""
        # Re-apply the public branding URL policy before placing it in the login page.
        if not (logo_url.startswith("/") and not logo_url.startswith("//") or logo_url.startswith("https://")):
            logo_url = ""
        return {"data": {"app_name": app_name.strip()[:60] or bound["name"],
                         "tagline": tagline.strip()[:120] or fallback["tagline"],
                         "logo_url": logo_url[:500]}}

    @app.post("/api/auth/login")
    def login(request: Request, body: dict = Body(...)):
        res = plane.identity.authenticate(str(body.get("email", "")), str(body.get("password", "")),
                                          ip=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"),
                                          totp_code=body.get("totp_code"))
        data = profile(res.context, request)
        if body.get("return_token"):
            data["token"] = res.token                                # for API clients; the Desk uses the HttpOnly cookie
        resp = JSONResponse({"data": data})
        resp.set_cookie(COOKIE, res.token, httponly=True, samesite="lax", secure=_https(request),
                        max_age=int(SESSION_IDLE.total_seconds()), path="/")
        return resp

    @app.post("/api/auth/logout")
    def logout(request: Request):
        token, source = _token(request)
        _check_csrf(request, source)
        plane.identity.logout(token)
        resp = JSONResponse({"data": {"signed_out": True}})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/api/auth/me")
    def me(request: Request):
        token, _ = _token(request)
        return {"data": profile(plane.identity.resolve(token), request)}

    @app.post("/api/auth/switch-company")
    def switch(request: Request, body: dict = Body(...)):
        token, source = _token(request)
        _check_csrf(request, source)
        auth = plane.identity.resolve(token)
        return {"data": plane.identity.switch_company(auth, str(body.get("company_id", "")))}

    @app.post("/api/auth/default-company")
    def default_company(request: Request, body: dict = Body(...)):
        token, source = _token(request)
        _check_csrf(request, source)
        auth = plane.identity.resolve(token)
        return {"data": {"default_company": plane.identity.set_default_company(auth, str(body.get("company_id") or "") or None)}}

    @app.post("/api/auth/change-password")
    def change_password(request: Request, body: dict = Body(...)):
        token, source = _token(request)
        _check_csrf(request, source)
        auth = plane.identity.resolve(token)
        if not body.get("new_password"):
            raise ValidationError("new_password is required")
        plane.identity.change_password(auth, str(body.get("current_password", "")), str(body["new_password"]))
        resp = JSONResponse({"data": {"changed": True, "sign_in_again": True}})
        resp.delete_cookie(COOKIE, path="/")
        return resp


    # Platform administration endpoints do not require an active company context; their own handlers
    # require a platform-administrator identity and operate only on the control plane.
    from .platform_admin import install_platform_admin_routes
    install_platform_admin_routes(app, plane)
