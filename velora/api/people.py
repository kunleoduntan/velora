"""People & Access for the company you are working in: list, add (one step), change roles, remove."""
from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse

from ..exceptions import ValidationError
from ..permissions import get_session


def _people():
    from ..company import current_company
    from ..controlplane.people import People
    here = current_company()
    plane = getattr(getattr(here, "directory", None), "plane", None)
    if here is None or plane is None:
        raise ValidationError("People are managed on a platform installation (one sign-in for many companies).",
                              advice={"hint": "In developer mode, sign in with the X-Velora-User header instead; on a platform installation open People & Access."})
    return People(plane), here.id


def install_people_routes(app: FastAPI, scope, run):
    @app.get("/api/people")
    def people_list(request: Request):
        def fn():
            svc, cid = _people(); s = get_session()
            return svc.list(s.user, s.roles, cid)
        return run(request, fn)

    @app.get("/api/people/options")
    def people_options(request: Request):
        def fn():
            from ..controlplane.people import access_profiles, known_roles
            s = get_session()
            if s.user != "Administrator" and "System Manager" not in s.roles:
                from ..exceptions import PermissionDenied
                raise PermissionDenied("Only a System Manager can manage people.")
            return {"profiles": access_profiles(), "roles": known_roles()}
        return run(request, fn)

    @app.post("/api/people")
    def people_add(request: Request, body: dict = Body(...)):
        def fn():
            from ..controlplane.people import access_profiles
            svc, cid = _people(); s = get_session()
            roles = list(body.get("roles") or [])
            chosen = set(body.get("profiles") or [])
            for p in access_profiles():
                if p["name"] in chosen: roles += p["roles"]
            return svc.add(s.user, s.roles, cid, email=str(body.get("email") or ""), full_name=str(body.get("full_name") or ""), roles=roles)
        out = run(request, fn)
        return JSONResponse(out, headers={"Cache-Control": "no-store"})       # may carry a one-time password

    @app.post("/api/people/{email}/roles")
    def people_roles(email: str, request: Request, body: dict = Body(...)):
        def fn():
            svc, cid = _people(); s = get_session()
            return svc.set_roles(s.user, s.roles, cid, email, list(body.get("roles") or []))
        return run(request, fn)

    @app.delete("/api/people/{email}")
    def people_remove(email: str, request: Request):
        def fn():
            svc, cid = _people(); s = get_session()
            return {"removed": svc.remove(s.user, s.roles, cid, email)}
        return run(request, fn)
