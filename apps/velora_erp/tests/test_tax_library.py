"""Every report in the Tax Report Library runs against a seeded ledger and returns well-formed rows."""
import json
import pathlib
from datetime import date

import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.permissions import session_as

from test_invoices_v08 import APPROVER, MAKER, approve_submit, setup
from test_tax_management import _rule
from velora_erp.tax import library

TYPES = {"Data", "Date", "Currency", "Float", "Int"}


def _seed(a):
    _rule(a, "VAT7", 7.5, a["vatout"].name)
    _rule(a, "VAT7IN", 7.5, a["vatin"].name)
    _rule(a, "WHT5C", 5, a["vatin"].name, tax_type="WHT")
    _rule(a, "CIT30", 30, None, tax_type="Income Tax")
    with session_as(MAKER):
        s = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="s",
                    lines=[{"account": a["rev"].name, "description": "Consulting", "amount": 5000, "tax_code": "VAT7"}]).insert()
        p = new_doc("Purchase Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["supp"].name, currency="NGN", exchange_rate=1, narration="p",
                    lines=[{"account": a["exp"].name, "description": "Supplies", "amount": 2000, "tax_code": "VAT7IN"}]).insert()
    s, p = approve_submit(s), approve_submit(p)
    with session_as(MAKER):
        approve_submit(new_doc("Tax Journal", title="w", posting_date=date.today(), currency="NGN", exchange_rate=1, narration="n",
                               lines=[{"party_type": "Customer", "party": a["cust"].name, "invoice_reference": s.name, "gross_amount": 2000, "tax_rule": "WHT5C"}]).insert())
    from velora_erp.tax import cit, service
    jur = get_list("Tax Jurisdiction", fields=["name"])[0]["name"]
    y = date.today().year
    c = new_doc("Income Tax Computation", title="CIT", jurisdiction=jur, period_start=date(y, 1, 1), period_end=date(y, 12, 31), income_tax_rule="cit30").insert(ignore_permissions=True)
    cit.calculate_computation(c.name)
    try:
        service.refresh_obligations()
    except Exception:
        pass


def test_every_library_report_runs_and_the_dispatcher_serves_it(tmp_path):
    from velora_erp.tax.report.tax_report_library.tax_report_library import execute
    a = setup(tmp_path)
    try:
        _seed(a)
        y = date.today().year
        names = library.available()
        assert len(names) >= 120
        assert len({id(library.REG[n]) for n in names}) >= len(names) - 25   # no name is merely another label for a report that is already there
        with session_as(APPROVER):
            bad = []
            for n in names:
                try:
                    cols, rows = library.run(n, date(y, 1, 1), date(y, 12, 31))
                    assert cols and all(len(c) == 3 and c[2] in TYPES for c in cols), "bad columns"
                    keys = {c[0] for c in cols}
                    for r in rows:
                        assert set(r) <= keys, f"row has unknown keys {sorted(set(r) - keys)}"
                except Exception as e:  # noqa: BLE001
                    bad.append(f"{n}: {type(e).__name__}: {str(e)[:160]}")
            assert not bad, "\n".join(bad)
            assert execute({"report": "VAT by Tax Rate"}) is not None          # period defaults to the year to date
            assert execute({"report": "Executive Tax Report", "from_date": date(y, 1, 1), "to_date": date(y, 12, 31)}) is not None
            cols, rows = library.run("VAT by Tax Rate", date(y, 1, 1), date(y, 12, 31))
            assert any(r.get("net_tax") == 225.0 and r.get("out") == 375.0 for r in rows)
            cols, rows = library.run("Tax Data Quality Scorecard", date(y, 1, 1), date(y, 12, 31))
            assert rows[-1]["area"] == "Overall"
            with pytest.raises(Exception):
                library.run("Penalty Computation", date(y, 1, 1), date(y, 12, 31))
    finally:
        velora.shutdown()


def test_report_json_options_match_the_registry():
    spec = json.loads((pathlib.Path(library.__file__).parent / "report" / "tax_report_library" / "tax_report_library.json").read_text())
    opts = next(f["options"] for f in spec["filters"] if f["fieldname"] == "report").split("\n")
    assert sorted(opts) == library.available()


def _run_all(**kw):
    bad = []
    for n in library.available():
        try:
            cols, rows = library.run(n, *kw["period"], kw.get("tax_type"), kw.get("jurisdiction"), kw.get("party"))
            assert cols and all(c[2] in TYPES for c in cols)
            for r in rows:
                assert set(r) <= {c[0] for c in cols}, sorted(set(r) - {c[0] for c in cols})
        except Exception as e:  # noqa: BLE001
            bad.append(f"{n}: {type(e).__name__}: {str(e)[:120]}")
    return bad


def test_nothing_fails_on_an_empty_book_or_with_any_filter(tmp_path):
    a = setup(tmp_path)
    try:
        y = date.today().year
        with session_as(APPROVER):
            assert not _run_all(period=(date(y, 1, 1), date(y, 12, 31)))                                  # nothing posted, no rules, no obligations
            assert not _run_all(period=(date(y, 12, 31), date(y, 1, 1)))                                  # dates the wrong way round
        _seed(a)
        with session_as(APPROVER):
            for kw in ({"period": (date.today(), date.today())}, {"period": (date(y - 3, 1, 1), date(y + 1, 12, 31))}, {"period": (date(y, 1, 1), date(y, 12, 31)), "tax_type": "VAT"},
                       {"period": (date(y, 1, 1), date(y, 12, 31)), "tax_type": "WHT", "party": a["cust"].name}, {"period": (date(y, 1, 1), date(y, 12, 31)), "jurisdiction": "no-such-place"},
                       {"period": (date(y - 1, 1, 1), date(y - 1, 12, 31))}):
                assert not _run_all(**kw), kw
    finally:
        velora.shutdown()
