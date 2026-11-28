"""Tax Management inside the ERP: engine, rules, invoice standardisation, ledger, returns, obligations, catalogue."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as

from test_invoices_v08 import APPROVER, MAKER, approve_submit, setup
from velora_erp.tax import engine as eng
from velora_erp.tax import service as tax

D = Decimal


def R(**kw):
    base = dict(code="VAT", tax_type="VAT", jurisdiction="NG", rate=D("7.5"))
    base.update(kw); return eng.Rule(**base)


# ---------------------------------------------------------------- engine (pure)

def test_inclusive_extraction_always_reconciles_to_the_gross():
    for gross in ("107.50", "100", "33.33", "0.07", "999999.99"):
        r = eng.calculate(R(), gross, tax_inclusive=True)
        assert r.taxable_amount + r.tax_amount == D(gross)


def test_credit_notes_give_negative_tax_for_every_method():
    t = R(code="T", method="tiered", tiers=((D(0), D(1000), D(10)), (D(1000), None, D(20))))
    assert eng.calculate(R(), "-100").tax_amount == D("-7.50")
    assert eng.calculate(t, "1500").tax_amount == D("200.00") and eng.calculate(t, "-1500").tax_amount == D("-200.00")
    assert eng.calculate(R(method="fixed", fixed_amount=D("50")), "-10").tax_amount == D("-50.00")


def test_fixed_needs_a_base_and_precision_is_a_rule_setting():
    assert eng.calculate(R(method="fixed", fixed_amount=D("50")), "0").tax_amount == D("0")
    assert eng.calculate(R(precision=0), "100").tax_amount == D("8")           # 7.5 rounds half up, no decimals


def test_recoverability_splits_the_tax_exactly():
    r = eng.calculate(R(recoverability_percent=D("60")), "1000")
    assert (r.tax_amount, r.recoverable_amount, r.non_recoverable_amount) == (D("75.00"), D("45.00"), D("30.00"))


@pytest.mark.parametrize("bad,msg", [
    (dict(rate=D("101")), "between 0 and 100"), (dict(recoverability_percent=D("101")), "Recoverability"), (dict(precision=9), "precision"),
    (dict(method="tiered", tiers=()), "at least one band"), (dict(method="tiered", tiers=((D(0), D(10), D(5)),)), "open-ended"),
    (dict(method="tiered", tiers=((D(0), D(10), D(5)), (D(20), None, D(6)))), "start where"), (dict(method="tiered", inclusive=True, tiers=((D(0), None, D(5)),)), "inclusive"),
    (dict(method="bogus"), "Unsupported"), (dict(effective_from=date(2026, 2, 1), effective_to=date(2026, 1, 1)), "Effective To")])
def test_invalid_configuration_is_refused(bad, msg):
    with pytest.raises(eng.TaxConfigError, match=msg):
        eng.validate_rule(R(**bad))


def test_rule_selection_prefers_category_and_rejects_ambiguity_and_gaps():
    a, b = R(code="STD"), R(code="FOOD", category="Food", rate=D("0"))
    assert eng.select_rule([a, b], "VAT", "NG", date(2026, 1, 1), "Food").code == "FOOD"
    assert eng.select_rule([a, b], "VAT", "NG", date(2026, 1, 1), None).code == "STD"
    with pytest.raises(eng.TaxConfigError, match="Ambiguous"):
        eng.select_rule([a, R(code="STD2")], "VAT", "NG", date(2026, 1, 1))
    with pytest.raises(LookupError):
        eng.select_rule([R(effective_from=date(2027, 1, 1))], "VAT", "NG", date(2026, 1, 1))


def test_withholding_net_payable():
    r = eng.calculate(R(tax_type="WHT", rate=D("5")), "10000")
    assert eng.withhold(r, "10000") == {"gross": D("10000"), "withheld": D("500.00"), "net_payable": D("9500.00")}


# ---------------------------------------------------------------- ERP integration

def _rule(a, code="VAT7", rate=7.5, account=None, **kw):
    j = get_list("Tax Jurisdiction", filters=[["jurisdiction_code", "=", "NG"]], fields=["name"])
    jur = j[0]["name"] if j else new_doc("Tax Jurisdiction", jurisdiction_code="ng", jurisdiction_name="Nigeria", authority="FIRS", currency="NGN").insert(ignore_permissions=True).name
    base = dict(rule_code=code, rule_name=code, tax_type="VAT", jurisdiction=jur, method="Percentage", rate=rate, effective_from=date(date.today().year, 1, 1), tax_account=account)
    base.update(kw)
    r = new_doc("Tax Rule", **base).insert(ignore_permissions=True)
    return approve_submit(r)


def test_rule_validation_approval_and_immutability(tmp_path):
    a = setup(tmp_path)
    try:
        with session_as(MAKER):
            j = new_doc("Tax Jurisdiction", jurisdiction_code="ng", jurisdiction_name="Nigeria").insert()
            assert j.jurisdiction_code == "NG"
            with pytest.raises(ValidationError, match="between 0 and 100"):
                new_doc("Tax Rule", rule_code="X", rule_name="X", tax_type="VAT", jurisdiction=j.name, method="Percentage", rate=150, effective_from=date(2026, 1, 1)).insert()
            with pytest.raises(ValidationError, match="liability"):
                new_doc("Tax Rule", rule_code="X", rule_name="X", tax_type="VAT", jurisdiction=j.name, method="Percentage", rate=5, effective_from=date(2026, 1, 1), tax_account=a["exp"].name).insert()
            with pytest.raises(ValidationError, match="Bands apply only"):
                new_doc("Tax Rule", rule_code="X", rule_name="X", tax_type="VAT", jurisdiction=j.name, method="Percentage", rate=5, effective_from=date(2026, 1, 1), tiers=[{"lower_limit": 0, "rate": 5}]).insert()
            first = new_doc("Tax Rule", rule_code="vat7", rule_name="VAT", tax_type="VAT", jurisdiction=j.name, method="Percentage", rate=7.5, effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30)).insert()
            assert first.rule_code == "VAT7"
            with pytest.raises(ValidationError, match="overlap"):
                new_doc("Tax Rule", rule_code="VAT7", rule_name="VAT", tax_type="VAT", jurisdiction=j.name, method="Percentage", rate=8, effective_from=date(2026, 6, 1)).insert()
        first = approve_submit(first)
        assert first.docstatus == 1 and first.approval_hash
        with pytest.raises(ValidationError):                                      # a submitted rule is immutable; change it by cancel and amend
            doc = get_doc("Tax Rule", first.name); doc.rate = 9; doc.save(ignore_permissions=True)
        assert [r.code for r in tax.load_rules(date(2026, 3, 1))] == ["VAT7"] and tax.load_rules(date(2026, 8, 1)) == []
    finally:
        velora.shutdown()


def test_invoice_lines_follow_the_approved_tax_code_and_the_setting_can_enforce_it(tmp_path):
    a = setup(tmp_path)
    try:
        _rule(a, "VAT7", 7.5, a["vatout"].name)
        _rule(a, "FLAT", 0, None, method="Fixed", fixed_amount=100)
        with session_as(MAKER):
            inv = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="x",
                          lines=[{"account": a["rev"].name, "description": "Consulting", "amount": 1000, "tax_code": "vat7"}]).insert()
            line = inv.lines[0]
            assert (line.tax_rate, line.tax_amount, line.tax_account) == (7.5, 75, a["vatout"].name) and inv.grand_total == 1075
            with pytest.raises(ValidationError, match="Only percentage"):
                new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="x",
                        lines=[{"account": a["rev"].name, "description": "y", "amount": 1000, "tax_code": "FLAT"}]).insert()
            # unknown code is allowed until the entity turns enforcement on
            ok = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="x",
                         lines=[{"account": a["rev"].name, "description": "legacy", "amount": 100, "tax_account": a["vatout"].name, "tax_rate": 5, "tax_amount": 5, "tax_code": "OLD"}]).insert()
            assert ok.lines[0].tax_rate == 5
        new_doc("Tax Settings", settings_name="Tax Settings", require_registered_codes=1).insert(ignore_permissions=True)
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="not an approved Tax Rule"):
                new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="x",
                        lines=[{"account": a["rev"].name, "description": "y", "amount": 100, "tax_account": a["vatout"].name, "tax_rate": 5, "tax_amount": 5, "tax_code": "OLD"}]).insert()
            with pytest.raises(ValidationError, match="needs a Tax Code"):
                new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="x",
                        lines=[{"account": a["rev"].name, "description": "y", "amount": 100, "tax_account": a["vatout"].name, "tax_rate": 5, "tax_amount": 5}]).insert()
            plain = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="x",
                            lines=[{"account": a["rev"].name, "description": "untaxed", "amount": 100}]).insert()
            assert plain.tax_amount == 0
    finally:
        velora.shutdown()


def _invoices(a):
    with session_as(MAKER):
        s = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="s",
                    lines=[{"account": a["rev"].name, "description": "Consulting", "amount": 1000, "tax_code": "VAT7"}]).insert()
        p = new_doc("Purchase Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["supp"].name, currency="NGN", exchange_rate=1, narration="p",
                    lines=[{"account": a["exp"].name, "description": "Supplies", "amount": 2000, "tax_code": "VAT7IN"}]).insert()
    return approve_submit(s), approve_submit(p)


def test_ledger_return_filing_and_obligation_lifecycle(tmp_path):
    a = setup(tmp_path)
    try:
        _rule(a, "VAT7", 7.5, a["vatout"].name)
        _rule(a, "VAT7IN", 7.5, a["vatin"].name, recoverability_percent=80)
        _invoices(a)
        y = date.today().year
        rows = tax.ledger_rows(date(y, 1, 1), date(y, 12, 31))
        assert sorted((r["section"], r["tax_code"], r["tax"]) for r in rows) == [("Input tax", "VAT7IN", D("150")), ("Output tax", "VAT7", D("75"))]
        jur = get_list("Tax Jurisdiction", fields=["name"])[0]["name"]
        ob = new_doc("Tax Obligation", tax_type="VAT", jurisdiction=jur, period_start=date(y, 1, 1), period_end=date(y, 12, 31), due_date=date(y, 12, 31) + timedelta(days=21)).insert(ignore_permissions=True)
        with pytest.raises(ValidationError, match="Calculate"):
            r = new_doc("Tax Return", tax_type="VAT", jurisdiction=jur, period_start=date(y, 1, 1), period_end=date(y, 12, 31), obligation=ob.name).insert(ignore_permissions=True)
            approve_submit(r)
        ret = new_doc("Tax Return", tax_type="VAT", jurisdiction=jur, period_start=date(y, 1, 1), period_end=date(y, 12, 31), obligation=ob.name).insert(ignore_permissions=True)
        out = tax.calculate_return(ret.name)
        assert (out["output_tax"], out["input_tax"], out["non_recoverable_tax"], out["net_payable"]) == ("75.00", "120.00", "30.00", "-45.00") or \
               (D(out["output_tax"]), D(out["input_tax"]), D(out["non_recoverable_tax"]), D(out["net_payable"])) == (D("75"), D("120"), D("30"), D("-45"))
        # the ledger moves after calculation: the return cannot be submitted until recalculated
        with session_as(MAKER):
            extra = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="late",
                            lines=[{"account": a["rev"].name, "description": "Late sale", "amount": 200, "tax_code": "VAT7"}]).insert()
        approve_submit(extra)
        with pytest.raises(ValidationError, match="ledger has changed"):
            approve_submit(get_doc("Tax Return", ret.name))
        tax.calculate_return(ret.name)
        sub = approve_submit(get_doc("Tax Return", ret.name))
        assert sub.docstatus == 1 and D(sub.output_tax) == D("90")
        with pytest.raises(ValidationError, match="reference"):
            tax.file_return(sub.name, " ")
        tax.file_return(sub.name, "FIRS-2026-001")
        assert get_doc("Tax Obligation", ob.name).status == "Filed"
        tax.record_outcome(sub.name, True, "ACK-1")
        done = get_doc("Tax Return", sub.name)
        assert done.return_status == "Accepted" and done.acknowledgement == "ACK-1" and get_doc("Tax Obligation", ob.name).status == "Accepted"
        with pytest.raises(ValidationError, match="filed return"):
            tax.record_outcome(sub.name, False)
    finally:
        velora.shutdown()


def test_unregistered_codes_are_reported_not_hidden_and_overdue_is_flagged(tmp_path):
    a = setup(tmp_path)
    try:
        _rule(a, "VAT7", 7.5, a["vatout"].name)
        with session_as(MAKER):
            s = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="s",
                        lines=[{"account": a["rev"].name, "description": "Old", "amount": 100, "tax_account": a["vatout"].name, "tax_rate": 5, "tax_amount": 5, "tax_code": "OLD"}]).insert()
        approve_submit(s)
        y = date.today().year
        lines, warnings = tax.build_return_lines("VAT", get_list("Tax Jurisdiction", fields=["name"])[0]["name"], date(y, 1, 1), date(y, 12, 31))
        assert lines == [] and "OLD" in warnings[0]
        jur = get_list("Tax Jurisdiction", fields=["name"])[0]["name"]
        ob = new_doc("Tax Obligation", tax_type="VAT", jurisdiction=jur, period_start=date(2025, 1, 1), period_end=date(2025, 1, 31), due_date=date(2025, 2, 21)).insert(ignore_permissions=True)
        assert ob.overdue == 1
        with pytest.raises(ValidationError, match="due date"):
            new_doc("Tax Obligation", tax_type="VAT", jurisdiction=jur, period_start=date(2025, 1, 1), period_end=date(2025, 1, 31), due_date=date(2025, 1, 15)).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_reports_run_and_calculator_applies_the_approved_rule(tmp_path):
    a = setup(tmp_path)
    try:
        _rule(a, "VAT7", 7.5, a["vatout"].name)
        _rule(a, "WHT5", 5, None, tax_type="WHT")
        _invoices_vat = None
        with session_as(MAKER):
            s = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="s",
                        lines=[{"account": a["rev"].name, "description": "c", "amount": 1000, "tax_code": "VAT7"}]).insert()
        approve_submit(s)
        j = get_list("Tax Jurisdiction", fields=["name"])[0]["name"]
        w = tax.calculate("WHT", j, 10000, date.today())
        assert w["withheld"] == "500.00" and w["net_payable"] == "9500.00"
        with pytest.raises(ValidationError, match="No tax rule"):
            tax.calculate("VAT", j, 100, date(2000, 1, 1))
        from velora_erp.tax.report.tax_ledger.tax_ledger import execute
        y = date.today().year
        with session_as(APPROVER):
            rb = execute({"from_date": date(y, 1, 1), "to_date": date(y, 12, 31)})
        assert rb is not None
    finally:
        velora.shutdown()


def test_catalogue_lists_only_reports_that_run():
    from pathlib import Path

    from velora_erp.tax import library
    c = tax.catalogue()
    assert len(c) > 120 and len({r["id"] for r in c}) == len(c)
    assert not any("csv_export" in r["features"] or "company" in r["filters"] for r in c)
    assert not any(r["status"] == "specification" for r in c)
    folders = {p.name for p in (Path(tax.__file__).parent / "report").iterdir() if p.is_dir() and not p.name.startswith("_")}
    for r in c:                      # every listed report has something behind it
        if r["status"] == "Tax Report Library":
            assert r["report_name"] in library.available(), r["report_name"]
        else:
            assert r["status"].lower().replace(" ", "_") in folders, r["status"]
