"""Every route must be describable and must not expose a stray `request` query parameter."""
from fastapi.testclient import TestClient


def _app():
    from velora.api.app import create_app
    return create_app()


def test_openapi_builds():
    app = _app()
    assert TestClient(app).get("/openapi.json").status_code == 200


def test_no_route_has_request_query_param():
    schema = _app().openapi()
    bad = [(p, m) for p, ops in schema["paths"].items() for m, op in ops.items()
           if any(x.get("name") == "request" and x.get("in") == "query" for x in op.get("parameters", []))]
    assert not bad, bad
