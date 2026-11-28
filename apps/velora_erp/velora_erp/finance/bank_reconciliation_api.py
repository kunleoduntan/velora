"""HTTP routes for the Bank Reconciliation centre. Registered through the ``api_routes_provider`` app hook."""
from fastapi import Body, Request
from velora.meta.registry import registry
from velora.permissions import check_permission
from velora_erp.finance import bank_reconciliation as svc


def _can(ptype):
    check_permission(registry.get("Bank Reconciliation"), ptype)


def install_routes(app, scope, run):
    base = "/api/bank-reconciliation"

    @app.get(f"{base}/workbench")
    def workbench(bank_account: str, request: Request, to_date: str | None = None):
        def fn():
            _can("read")
            return svc.workbench(bank_account, to_date)
        return run(request, fn)

    @app.get(f"{base}/compute")
    def compute(bank_account: str, to_date: str, request: Request, from_date: str | None = None, opening: str | None = None, closing: str | None = None):
        def fn():
            _can("read")
            res = svc.compute(bank_account, from_date, to_date, opening if opening not in (None, "") else None, closing or 0)
            res["items"] = res["items"][:500]
            res.pop("cleared_group_ids", None)
            return res
        return run(request, fn)

    @app.post(f"{base}/import")
    def import_statement(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return svc.import_statement(body.get("bank_account"), content=body.get("content"), content_base64=body.get("content_base64"), filename=body.get("filename") or "",
                                        fmt=body.get("format"), amount_sign=body.get("amount_sign") or "credit_positive", column_map=body.get("column_map"), auto=body.get("auto", True))
        return run(request, fn)

    @app.post(f"{base}/auto")
    def auto(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return svc.run_auto(body.get("bank_account"), to_date=body.get("to_date"), post=body.get("post"))
        return run(request, fn)

    @app.post(f"{base}/match")
    def manual(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return svc.manual_match(body.get("bank_account"), body.get("lines") or [], body.get("records") or [], body.get("reason"))
        return run(request, fn)

    @app.post(f"{base}/confirm")
    def confirm(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return {"confirmed": svc.confirm_groups(body.get("groups") or [])}
        return run(request, fn)

    @app.post(f"{base}/reject")
    def reject(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return {"rejected": svc.reject_groups(body.get("groups") or [])}
        return run(request, fn)

    @app.post(f"{base}/unmatch")
    def unmatch(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return {"released": sum(svc.unmatch(g) for g in (body.get("groups") or []))}
        return run(request, fn)

    @app.post(f"{base}/ignore")
    def ignore(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return {"ignored": svc.ignore_lines(body.get("lines") or [], body.get("reason") or "")}
        return run(request, fn)

    @app.post(f"{base}/restore")
    def restore(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return {"restored": svc.restore_lines(body.get("lines") or [])}
        return run(request, fn)

    @app.post(f"{base}/post")
    def post(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            svc.code_unmatched(body.get("bank_account"))
            return svc.post_coded_lines(body.get("bank_account"))
        return run(request, fn)

    @app.post(f"{base}/opening-clearance")
    def opening(request: Request, body: dict = Body(...)):
        def fn():
            _can("submit")
            return svc.clear_opening_entries(body.get("bank_account"), body.get("before_date"))
        return run(request, fn)
