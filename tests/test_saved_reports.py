import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

import velora
from velora import db, new_doc
from velora.api import create_app
from velora.db.system import export_log
from velora.exceptions import DoesNotExistError, PermissionDenied, ValidationError
from velora.reporting.runner import prepare_adhoc, run_adhoc
from velora.reporting.saved import MAX_SPEC_BYTES, create_saved, delete_saved, export_saved, get_saved, list_saved, run_saved, update_saved

SAM = velora.Session("sam", frozenset({"Sales User"}))
SAM2 = velora.Session("sam2", frozenset({"Sales User"}))
BOSS = velora.Session("boss", frozenset({"System Manager"}))
NOBODY = velora.Session("nobody", frozenset())
H = lambda user, roles: {"X-Velora-User": user, "X-Velora-Roles": roles}
SALES_H, SALES2_H, ADMIN_H = H("sam", "Sales User"), H("sam2", "Sales User"), H("boss", "System Manager")

SPEC = {"doctype": "Customer", "group_by": ["customer_group", "status"], "title": "Credit by group",
        "measures": [{"fn": "count", "label": "Customers"}, {"fn": "sum", "field": "credit_limit", "label": "Credit Limit"}]}


def seed():
    for g in ("Retail", "Wholesale"):
        new_doc("Customer Group", group_name=g).insert()
    for n, g, s, lim in (("Acme", "Retail", "Active", 1000), ("Beta", "Retail", "Blocked", 500), ("Cato", "Wholesale", "Active", 2500)):
        new_doc("Customer", customer_name=n, customer_group=g, status=s, credit_limit=lim).insert()


def as_(session):
    return velora.session_as(session)


# ============================ validation (before anything runs) ============================
@pytest.mark.parametrize("patch,frag", [
    ({"bogus": 1}, "Unknown report setting"),
    ({"group_by": ["nope"]}, "Invalid field"),
    ({"group_by": []}, "group_by needs"),
    ({"measures": [{"fn": "sum", "field": "customer_name"}]}, "Invalid field"),
    ({"measures": [{"fn": "mode", "field": "credit_limit"}]}, "measure fn must be"),
    ({"date_bucket": "month"}, "date bucket"),
    ({"group_by": ["status"], "date_field": "customer_name", "date_bucket": "month"}, "date bucket"),
    ({"filters": ["x"]}, "triples"),
    ({"filters": [["status", "~", "x"]]}, "Unsupported filter operator"),
    ({"filters": [["nope", "=", 1]]}, "unknown field"),
    ({"filters": [["credit_limit", "<", "abc"]]}, "not a valid"),
    ({"filters": [["status", "=", "a"]] * 21}, "At most 20"),
])
def test_prepare_adhoc_refuses_bad_specs_without_running_them(site, patch, frag):
    with pytest.raises(ValidationError, match=frag):
        prepare_adhoc({**SPEC, **patch})


def test_prepare_adhoc_errors_for_unknown_doctype_and_missing_permission(site):
    with pytest.raises(DoesNotExistError):
        prepare_adhoc({**SPEC, "doctype": "Ghost"})
    with as_(NOBODY):
        with pytest.raises(PermissionDenied):
            prepare_adhoc(SPEC)
    with pytest.raises(ValidationError):
        prepare_adhoc("not a dict")


def test_adhoc_filters_read_as_plain_language_in_the_report_and_the_excel(site):
    from velora.reporting.excel import report_to_xlsx
    seed()
    flt = [["credit_limit", ">=", 1000], ["status", "!=", "Blocked"], ["status", "in", ["Active", "Inactive"]], ["customer_name", "like", "%a%"],
           ["credit_limit", "between", [100, 5000]], ["email", "is", "not set"], ["customer_group", "=", "Retail"]]
    r = run_adhoc({**SPEC, "filters": flt})
    assert r.filters == [("Credit Limit is at least 1000", ""), ("Status is not Blocked", ""), ("Status is one of Active, Inactive", ""), ("Customer Name contains a", ""),
                         ("Credit Limit is between 100 and 5000", ""), ("Email Address is not set", ""), ("Customer Group is Retail", "")]
    ws = __import__("openpyxl").load_workbook(__import__("io").BytesIO(report_to_xlsx(r))).active
    line = next(c.value for row in ws.iter_rows() for c in row if "Filters:" in str(c.value))
    assert "Filters: Credit Limit is at least 1000; Status is not Blocked;" in line and "= " not in line      # no stray '=' for plain-language filters


# ============================ lifecycle ============================
def test_save_load_run_update_delete(site):
    seed()
    with as_(SAM):
        saved = create_saved("Credit by group", SPEC)
        assert saved["id"].startswith("SR-") and saved["owner"] == "sam" and saved["doctype"] == "Customer" and saved["can_edit"] and not saved["shared"]
        assert get_saved(saved["id"])["spec"]["measures"][1]["label"] == "Credit Limit"
        res = run_saved(saved["id"])
        assert res.title == "Credit by group" and res.rows[-1].type == "total" and res.rows[-1].values["m_1"] == 4000.0
        upd = update_saved(saved["id"], name="Credit v2", spec={**SPEC, "group_by": ["status"]})
        assert upd["name"] == "Credit v2" and upd["spec"]["group_by"] == ["status"]
        assert [r["name"] for r in list_saved()] == ["Credit v2"] and "spec" not in list_saved()[0]
        delete_saved(saved["id"])
        assert list_saved() == []
        with pytest.raises(DoesNotExistError):
            get_saved(saved["id"])


def test_names_are_unique_per_owner_and_validated(site):
    with as_(SAM):
        a = create_saved("Mine", SPEC)
        with pytest.raises(ValidationError, match="already have"):
            create_saved("Mine", SPEC)
        b = create_saved("Other", SPEC)
        with pytest.raises(ValidationError, match="already have"):
            update_saved(b["id"], name="Mine")
        for bad in ("", "   ", "x" * 101, "bad\x07name", None):
            with pytest.raises(ValidationError, match="name"):
                create_saved(bad, SPEC)
    with as_(SAM2):
        create_saved("Mine", SPEC)                                     # another person may use the same name
    assert a["id"]


def test_invalid_or_forbidden_definitions_cannot_be_saved(site):
    with as_(SAM):
        with pytest.raises(ValidationError):
            create_saved("Bad", {**SPEC, "group_by": ["nope"]})
        with pytest.raises(ValidationError, match="too large"):
            create_saved("Big", {**SPEC, "title": "x" * (MAX_SPEC_BYTES + 1)})
        saved = create_saved("Ok", SPEC)
        with pytest.raises(ValidationError):
            update_saved(saved["id"], spec={**SPEC, "filters": [["status", "~", 1]]})
        assert get_saved(saved["id"])["spec"] == SPEC | {}            # a failed update changed nothing
    with as_(NOBODY):
        with pytest.raises(PermissionDenied):
            create_saved("Sneaky", SPEC)                               # no read on Customer: cannot even save a report on it


# ============================ visibility, sharing, ownership ============================
def test_private_reports_are_invisible_and_shared_ones_visible(site):
    with as_(SAM):
        private = create_saved("Private", SPEC)
    with as_(SAM2):
        assert list_saved() == []
        with pytest.raises(DoesNotExistError):                         # indistinguishable from "does not exist"
            get_saved(private["id"])
        with pytest.raises(DoesNotExistError):
            run_saved(private["id"])
    with as_(BOSS):
        shared = create_saved("Company credit", SPEC, shared=True)
    with as_(SAM2):
        got = get_saved(shared["id"])
        assert got["shared"] and got["owner"] == "boss" and not got["can_edit"]
        assert [r["name"] for r in list_saved()] == ["Company credit"]


def test_sharing_is_for_system_managers_and_edits_for_owner_or_manager(site):
    with as_(SAM):
        with pytest.raises(PermissionDenied, match="share"):
            create_saved("S", SPEC, shared=True)
        mine = create_saved("Mine", SPEC)
        with pytest.raises(PermissionDenied, match="share"):
            update_saved(mine["id"], shared=True)
    with as_(BOSS):
        shared = create_saved("Shared", SPEC, shared=True)
        with pytest.raises(DoesNotExistError):
            update_saved(mine["id"], name="peek")                                                # a PRIVATE report is private - even from managers
        update_saved(shared["id"], shared=False)                                                 # the owner may unshare
    with as_(SAM2):
        assert list_saved() == []
    with as_(BOSS):
        update_saved(shared["id"], shared=True)
    with as_(SAM2):
        with pytest.raises(PermissionDenied, match="owner or a System Manager"):
            update_saved(shared["id"], name="hijack")
        with pytest.raises(PermissionDenied, match="owner or a System Manager"):
            delete_saved(shared["id"])
    with as_(SAM):
        with pytest.raises(PermissionDenied):
            delete_saved(shared["id"])
    with as_(velora.Session("boss2", frozenset({"System Manager"}))):
        assert update_saved(shared["id"], name="Renamed by another manager")["name"] == "Renamed by another manager"   # managers administer SHARED reports
        delete_saved(shared["id"])


def test_a_shared_report_shares_the_definition_never_the_data(site):
    seed()
    with as_(BOSS):
        shared = create_saved("Group credit", {"doctype": "Customer Group", "group_by": ["name"], "measures": [{"fn": "count"}]}, shared=True)
    with as_(SAM):
        assert run_saved(shared["id"]).rows                          # Sales User may read Customer Group ...
        with pytest.raises(PermissionDenied, match="export"):
            export_saved(shared["id"])                               # ... but has no export permission there
    with as_(NOBODY):
        assert list_saved() == []                                    # no read on the DocType: not even listed
        with pytest.raises(PermissionDenied):
            run_saved(shared["id"])
    with as_(BOSS):
        data, filename = export_saved(shared["id"])
        assert data[:2] == b"PK" and filename.endswith(".xlsx")


def test_deleting_the_doctype_data_access_is_rechecked_at_run_time(site):
    with as_(BOSS):
        shared = create_saved("Credit", SPEC, shared=True)
    with as_(velora.Session("restricted", frozenset({"Some Other Role"}))):
        with pytest.raises(PermissionDenied):
            run_saved(shared["id"])


# ============================ API ============================
@pytest.fixture
def client(site):
    return TestClient(create_app(auto_init=False))


def test_saved_report_api_end_to_end(client, site):
    seed()
    r = client.post("/api/saved-reports", json={"name": "Credit by group", "spec": SPEC}, headers=SALES_H)
    assert r.status_code == 201
    rid = r.json()["data"]["id"]
    assert client.get("/api/saved-reports", headers=SALES_H).json()["data"][0]["name"] == "Credit by group"
    assert client.get(f"/api/saved-report/{rid}", headers=SALES_H).json()["data"]["spec"]["title"] == "Credit by group"
    run = client.post(f"/api/saved-report/{rid}/run", headers=SALES_H).json()["data"]
    assert run["title"] == "Credit by group" and run["rows"][-1]["values"]["m_1"] == 4000.0
    x = client.post(f"/api/saved-report/{rid}/export", headers=SALES_H)
    assert x.status_code == 200 and x.headers["content-type"].startswith("application/vnd.openxmlformats")
    ws = load_workbook(io.BytesIO(x.content)).active
    assert ws["A1"].value == "Credit by group" and any(str(c.value).startswith("=SUM(") for row in ws.iter_rows() for c in row)
    with db.transaction() as conn:
        log = conn.execute(select(export_log).where(export_log.c.scope == "report")).mappings().all()
    assert len(log) == 1 and log[0]["owner"] == "sam"
    assert client.put(f"/api/saved-report/{rid}", json={"name": "Renamed"}, headers=SALES_H).json()["data"]["name"] == "Renamed"
    assert client.delete(f"/api/saved-report/{rid}", headers=SALES_H).json()["data"] == {"deleted": rid}
    assert client.get(f"/api/saved-report/{rid}", headers=SALES_H).status_code == 404


def test_saved_report_api_permissions_and_errors(client, site):
    rid = client.post("/api/saved-reports", json={"name": "Mine", "spec": SPEC}, headers=SALES_H).json()["data"]["id"]
    assert client.get(f"/api/saved-report/{rid}", headers=SALES2_H).status_code == 404                      # someone else's private report
    assert client.post(f"/api/saved-report/{rid}/run", headers=SALES2_H).status_code == 404
    assert client.post("/api/saved-reports", json={"name": "S", "spec": SPEC, "shared": True}, headers=SALES_H).status_code == 403
    sh = client.post("/api/saved-reports", json={"name": "Shared", "spec": SPEC, "shared": True}, headers=ADMIN_H).json()["data"]["id"]
    assert client.put(f"/api/saved-report/{sh}", json={"name": "x"}, headers=SALES2_H).status_code == 403
    assert client.delete(f"/api/saved-report/{sh}", headers=SALES2_H).status_code == 403
    assert client.post("/api/saved-reports", json={"name": "Bad", "spec": {**SPEC, "group_by": ["nope"]}}, headers=SALES_H).status_code == 422
    assert client.post("/api/saved-reports", json={"name": "Mine", "spec": SPEC}, headers=SALES_H).status_code == 422          # duplicate name
    assert client.get("/api/saved-reports").status_code == 401
    assert [r["name"] for r in client.get("/api/saved-reports", headers=SALES2_H).json()["data"]] == ["Shared"]


def test_list_valued_filters_actually_filter_the_data(site):
    """Regression: 'is one of' / 'between' were stringified before reaching the query engine, so these reports failed."""
    seed()                                            # Acme Retail/Active 1000, Beta Retail/Blocked 500, Cato Wholesale/Active 2500
    base = {"doctype": "Customer", "group_by": ["status"], "measures": [{"fn": "count"}, {"fn": "sum", "field": "credit_limit"}]}
    total = lambda r: (r.rows[-1].values["m_0"], r.rows[-1].values["m_1"])
    assert total(run_adhoc({**base, "filters": [["customer_group", "in", ["Retail"]]]})) == (2.0, 1500.0)
    assert total(run_adhoc({**base, "filters": [["credit_limit", "between", [400, 1200]]]})) == (2.0, 1500.0)
    assert total(run_adhoc({**base, "filters": [["status", "not in", ["Blocked"]]]})) == (2.0, 3500.0)
    assert total(run_adhoc({**base, "filters": [["customer_name", "like", "%a%"], ["credit_limit", ">", 600]]})) == (2.0, 3500.0)


@pytest.mark.parametrize("rid", ["", "x", "SR-", "SR-ZZZZZZZZ", "SR-abcdef123", "sr-abcdef12", "SR-abcdef12\x00", "\x00", "a" * 3000, "SR-abcdef12 ", "../etc"])
def test_malformed_report_ids_are_simply_not_found(site, rid):
    """Regression (PostgreSQL): a NUL byte in the id used to crash the request with a database error."""
    with as_(SAM):
        for fn in (get_saved, run_saved, export_saved, delete_saved):
            with pytest.raises(DoesNotExistError):
                fn(rid)
        with pytest.raises(DoesNotExistError):
            update_saved(rid, name="x")
