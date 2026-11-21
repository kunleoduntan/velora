"""Regression tests for the concurrent-posting defects found in the independent v1.4.0 review."""
import os
import threading
import uuid
from datetime import date

import pytest



# (Maker-checker, who may approve and the independent-editor control are now settings of each company's approval
#  workflow: see test_finance_workflow_v284.py. Only the concurrent-posting regression tests remain here.)


PG = os.environ.get("VELORA_TEST_PG_URL")


@pytest.mark.skipif(not PG, reason="set VELORA_TEST_PG_URL to a disposable PostgreSQL database to run the concurrency tests")
def test_concurrent_identical_postings_all_return_the_one_batch_on_postgresql():
    import velora
    from velora import db, new_doc
    from velora_erp.finance.engine import post_financial_transaction
    from velora_erp.setup import after_install
    velora.configure(db_url=PG, apps=["velora_erp"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    tag = uuid.uuid4().hex[:6].upper(); y = date.today().year     # use an EMPTY disposable database: two open periods covering today would be ambiguous
    for doctype, kw in (
        ("Financial Year", dict(year_name=f"FY-{tag}", start_date=date(y, 1, 1), end_date=date(y, 12, 31), status="Open", is_current=0)),
        ("Financial Period", dict(period_name=f"P-{tag}", financial_year=f"FY-{tag}", period_number=1, start_date=date(y, 1, 1), end_date=date(y, 12, 31), status="Open")),
        ("Account Group", dict(group_code=f"A{tag}", group_name="A", root_type="Asset", is_group=0)),
        ("Account Group", dict(group_code=f"E{tag}", group_name="E", root_type="Equity", is_group=0)),
    ):
        try:
            new_doc(doctype, **kw).insert(ignore_permissions=True)
        except Exception as exc:                                  # noqa: BLE001
            raise AssertionError(f"test setup failed for {doctype}: {exc}") from exc
    bank = new_doc("Account", account_code=f"B{tag}", account_name="Bank", account_group=f"A{tag}", account_type="BANK", is_control_account=1, control_account_type="Bank").insert(ignore_permissions=True)
    eq = new_doc("Account", account_code=f"Q{tag}", account_name="Eq", account_group=f"E{tag}", account_type="EQUITY").insert(ignore_permissions=True)

    def payload(src):
        return dict(source_doctype="Concurrency Test", source_name=src, posting_date=date.today(), currency="NGN",
                    lines=[{"account": bank.name, "debit": "10.00", "credit": "0"}, {"account": eq.name, "debit": "0", "credit": "10.00"}])

    def race(n, fn):
        out, bar = [], threading.Barrier(n)

        def run(i):
            bar.wait()
            try:
                out.append(("ok", fn(i).name))
            except Exception as exc:                              # noqa: BLE001
                out.append(("err", f"{type(exc).__name__}: {exc}"))
        ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
        [t.start() for t in ts]; [t.join() for t in ts]
        return out

    top = race(8, lambda i: post_financial_transaction(**payload(f"TOP-{tag}")))
    assert [x for x in top if x[0] == "err"] == [] and len({x[1] for x in top}) == 1, top

    def nested(i):
        with db.transaction():                                    # how a document's submit hook calls the engine
            return post_financial_transaction(**payload(f"NEST-{tag}"))
    inner = race(8, nested)
    assert [x for x in inner if x[0] == "err"] == [] and len({x[1] for x in inner}) == 1, inner
