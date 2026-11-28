from velora.api.platform import _wanted_company


class _Req:
    def __init__(self, path, q, headers=None, method="GET"):
        from types import SimpleNamespace as N
        self.method = method
        self.url = N(path=path)
        self.query_params = q
        self.headers = {"host": "x", **(headers or {})}


class _Plane:
    class registry:
        @staticmethod
        def company_for_domain(h):
            return None


def test_print_url_company_query_accepted_only_for_print_get():
    assert _wanted_company(_Plane, _Req("/api/print/a/b/c", {"company": "CO-1"})) == "CO-1"
    assert _wanted_company(_Plane, _Req("/api/doc/x", {"company": "CO-1"})) is None
    assert _wanted_company(_Plane, _Req("/api/print/a/b/c", {"company": "CO-1"}, {"x-velora-company": "CO-2"})) == "CO-2"
