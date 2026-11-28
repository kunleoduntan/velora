"""SASB structure, Excel import, responses, ISSB S2.32 signal."""
import io
from datetime import date

import pytest
import velora
from velora import get_list, new_doc
from velora.permissions import Session, session_as

from velora_governance.governance.services import sasb_catalog as sasb, issb_checklist as issb

ADMIN = Session("Administrator", frozenset({"System Manager"}))
APPS = ["velora_notify", "velora_erp", "velora_projectone", "velora_admin", "velora_governance"]


@pytest.fixture
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 's.db'}", apps=APPS, developer_mode=True)
    velora.init(); velora.migrate()
    from velora_governance.setup import after_install
    with session_as(ADMIN):
        after_install()
        yield


def _entity():
    t = get_list("Governance Entity Type", fields=["name"], limit=1)[0]["name"]
    e = new_doc("Governance Entity", entity_name="Sasb Co", legal_name="Sasb Company Limited", country="Nigeria", entity_type=t).insert()
    new_doc("Sustainability Reporting Period", governance_entity=e.name, period_name="FY2026", period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), period_type="Annual", period_status="Data Collection").insert()
    return e


def _book(rows_i, rows_m):
    from openpyxl import Workbook
    wb = Workbook(); a = wb.active; a.title = "Industries"; a.append(sasb.INDUSTRY_COLS)
    for r in rows_i: a.append(r)
    b = wb.create_sheet("Metrics"); b.append(sasb.METRIC_COLS)
    for r in rows_m: b.append(r)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_nothing_licensed_is_preloaded_and_template_reads_back(site):
    assert get_list("SASB Industry", fields=["name"]) == [] and get_list("SASB Metric", fields=["name"]) == []
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(sasb.template_workbook()))
    assert wb.sheetnames[:2] == ["Industries", "Metrics"] and [c.value for c in wb["Metrics"][1]] == sasb.METRIC_COLS


def test_import_is_idempotent_reports_row_errors_and_rejects_bad_files(site):
    data = _book([["IND-1", "Test Industry", "Test Sector", "2023"]],
                 [["M-1", "IND-1", "Energy", "Energy used", "Quantitative", "GJ", ""],
                  ["M-2", "IND-1", "Energy", "Describe energy strategy", "Discussion and analysis", "", ""],
                  ["M-3", "NOPE", "", "Orphan", "", "", ""],
                  ["M-4", "IND-1", "", "Bad category", "Weird", "", ""]])
    r = sasb.import_workbook(data)
    assert (r["industries_created"], r["metrics_created"], len(r["errors"])) == (1, 2, 2)
    r2 = sasb.import_workbook(data)
    assert (r2["industries_created"], r2["metrics_created"], r2["industries_updated"], r2["metrics_updated"]) == (0, 0, 1, 2)
    with pytest.raises(Exception, match="not a readable Excel"):
        sasb.import_workbook(b"not excel")


def test_responses_fill_from_data_points_need_explanations_and_feed_the_s2_32_signal(site):
    e = _entity()
    cat = get_list("Sustainability Metric Category", fields=["name"], limit=1)[0]["name"]
    unit = get_list("Sustainability Unit", fields=["name"], limit=1)[0]["name"]
    own = new_doc("Sustainability Metric", metric_code="OWN-EN", metric_name="Energy", category=cat, default_unit=unit, data_type="Numeric", frequency="Annual", active=1).insert()
    new_doc("Sustainability Data Point", governance_entity=e.name, metric=own.name, reporting_period="FY2026", data_type="Numeric", value=420, unit=unit, data_date=date(2026, 12, 31), verification_status="Reviewed").insert()
    sasb.import_workbook(_book([["IND-1", "Test Industry", "", ""]], [["M-1", "IND-1", "Energy", "Energy used", "Quantitative", "GJ", "OWN-EN"], ["M-2", "IND-1", "Energy", "Strategy", "Discussion and analysis", "", ""]]))
    with pytest.raises(Exception, match="SASB Adoption"):
        sasb.generate_responses(e.name, "FY2026")
    ind = get_list("SASB Industry", fields=["name"])[0]["name"]
    new_doc("SASB Adoption", governance_entity=e.name, industry=ind, basis="Our activities", active=1).insert()
    with pytest.raises(Exception, match="already has"):
        new_doc("SASB Adoption", governance_entity=e.name, industry=ind).insert()
    assert sasb.generate_responses(e.name, "FY2026") == {"created": 2, "filled_from_data_points": 1, "industries": 1}
    assert sasb.generate_responses(e.name, "FY2026")["created"] == 0
    assert sasb.signal(e.name, "FY2026")[0] is False
    rows = {r["sasb_metric"]: r for r in get_list("SASB Metric Response", fields=["name", "sasb_metric", "response_status", "value"])}
    m1 = get_list("SASB Metric", filters=[["metric_code", "=", "M-1"]], fields=["name"])[0]["name"]
    m2 = get_list("SASB Metric", filters=[["metric_code", "=", "M-2"]], fields=["name"])[0]["name"]
    assert rows[m1]["response_status"] == "Reported" and rows[m1]["value"] == 420
    d = velora.get_doc("SASB Metric Response", rows[m2]["name"]); d.response_status = "Omitted"
    with pytest.raises(Exception, match="Explain why"):
        d.save()
    d.omission_reason = "Not material to our activities"; d.save()
    ok, detail = sasb.signal(e.name, "FY2026")
    assert ok and "1 reported, 1 omitted" in detail
    assert issb.system_signals(e.name, "FY2026")["sasb"][0] is True
