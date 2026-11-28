"""HTTP surface of Velora Governance: its permission-aware service functions, reached through ONE route.

Every function in api.py that governance marked as callable (`@frappe.whitelist()`) is registered by the host adapter; this route runs exactly those
and nothing else. Each function checks the caller's permissions itself, and the framework's request wrapper supplies the session and transaction."""
from fastapi import Body, FastAPI, Request


def install_routes(app: FastAPI, scope, run):
    from velora.exceptions import DoesNotExistError, ValidationError
    from velora_governance import api  # noqa: F401  (importing registers the callable functions)
    from velora_governance.runtime import host

    @app.get("/api/governance/functions")
    def governance_functions(request: Request):
        return run(request, lambda: sorted(host.whitelisted))

    @app.post("/api/governance/call/{function}")
    def governance_call(function: str, request: Request, body: dict = Body(default={})):
        def go():
            fn = host.whitelisted.get(function)
            if fn is None: raise DoesNotExistError(f"There is no governance function called {function}")
            try:
                return fn(**(body or {}))
            except TypeError as exc:
                if "argument" in str(exc): raise ValidationError(f"{function}: {exc}") from None
                raise
        return run(request, go)
