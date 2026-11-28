"""Data Import and Export for any DocType."""
import csv
import io
import json
from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from velora import dataimport as di
from velora import db, get_doc, get_list, new_doc
from velora.api import create_app
from velora.cli import main
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import Session, session_as

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
CSV_CUSTOMERS = (
    "Customer Name *,Email,Customer Group,Status,Credit Limit,Tax Exempt\n"
    "Acme Ltd,info@acme.ng,Retail,Active,\"1,500,000.50\",yes\n"
    "Bola Stores,bola@x.ng,Retail,Blocked,₦250000,no\n")


def groups(*names):
    for n in names:
        new_doc("Customer Group", group_name=n).insert()


def imp(doctype, text, name="data.csv", **opt):
    data = text.encode() if isinstance(text, str) else text
    return di.import_file(doctype, data, name, di.Options(**opt))


def customers():
    return {c["customer_name"]: c for c in get_list("Customer", fields=["name", "customer_name", "email", "customer_group", "status", "credit_limit", "tax_exempt"], ignore_permissions=True)}


# ============================== reading files ==============================
def test_csv_columns_are_matched_by_label_or_fieldname_in_any_order_ignoring_case_and_stars(site):
    groups("Retail")
    rep = imp("Customer", "status,CUSTOMER_NAME,customer group,Credit Limit\nActive,Acme,Retail,10\n")
    assert rep.created == 1 and rep.failed == 0 and rep.unknown_columns == []
    c = customers()["Acme"]
    assert c["status"] == "Active" and c["customer_group"] == "Retail" and c["credit_limit"] == 10


def test_a_full_csv_with_money_checks_and_links(site):
    groups("Retail")
    rep = imp("Customer", CSV_CUSTOMERS)
    assert (rep.total, rep.created, rep.failed) == (2, 2, 0)
    c = customers()
    assert c["Acme Ltd"]["credit_limit"] == D("1500000.50") and c["Acme Ltd"]["tax_exempt"] == 1 and c["Bola Stores"]["credit_limit"] == 250000 and c["Bola Stores"]["tax_exempt"] == 0
    assert c["Acme Ltd"]["name"].startswith("CUST-") and rep.names == [c["Acme Ltd"]["name"], c["Bola Stores"]["name"]]          # the naming series applies


@pytest.mark.parametrize("raw,enc", [("Customer Name;Email\nÀcmé Ọláolúwa;a@b.ng\n", "utf-8-sig"), ("Customer Name\tEmail\nAcmé Ọláolúwa\ta@b.ng\n", "utf-8"), ("Customer Name,Email\nCafé Ltd,a@b.ng\n", "cp1252")])
def test_other_delimiters_and_encodings_are_understood(site, raw, enc):
    rep = imp("Customer", raw.encode(enc, errors="replace") if enc == "cp1252" else raw.encode(enc))
    assert rep.created == 1 and rep.failed == 0
    assert len(customers()) == 1


def xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_excel_files_including_real_dates_numbers_and_booleans(site):
    groups("Retail")
    data = xlsx([["Customer Name", "Credit Limit", "Tax Exempt", "Customer Group"], ["Acme", 1500.5, True, "Retail"], ["Bola", 0, False, "Retail"], [None, None, None, None]])
    rep = imp("Customer", data, "customers.xlsx")
    assert (rep.created, rep.failed, rep.total) == (2, 0, 2)                                                           # the blank row is skipped
    assert customers()["Acme"]["credit_limit"] == D("1500.5") and customers()["Acme"]["tax_exempt"] == 1
    c = new_doc("Customer", customer_name="X").insert()
    so = xlsx([["Customer", "Order Date", "Items.Description", "Items.Qty", "Items.Rate"], [c.name, date(2026, 3, 2), "Widget", 2, 100]])
    rep = imp("Sales Order", so, "orders.xlsx")
    assert rep.created == 1 and get_doc("Sales Order", rep.names[0]).order_date == date(2026, 3, 2)                       # an Excel date cell arrives as a real date


def test_json_files_in_three_shapes(site):
    groups("Retail")
    doc = {"customer_name": "J1", "customer_group": "Retail", "contacts": [{"contact_name": "Ada", "phone": "0803"}]}
    for shape in ([doc], {"data": [{**doc, "customer_name": "J2"}]}, {"docs": [{**doc, "customer_name": "J3"}]}):
        assert imp("Customer", json.dumps(shape), "x.json").created == 1
    assert set(customers()) == {"J1", "J2", "J3"}
    assert [c.contact_name for c in get_doc("Customer", customers()["J1"]["name"]).contacts] == ["Ada"]


@pytest.mark.parametrize("data,name,frag", [(b"", "a.csv", "empty"), (b"Customer Name\n", "a.csv", "no data rows"), (b"zzz,yyy\n1,2\n", "a.csv", "None of the column headings"), (b"x", "a.exe", "Unsupported file type"),
                                            (b"not xlsx", "a.xlsx", "not a readable Excel"), (b"{ nope", "a.json", "not valid JSON"), (b'{"x": 1}', "a.json", "list of objects"), (b"[1, 2]", "a.json", "list of objects"),
                                            (b"Customer Name,customer_name\nA,B\n", "a.csv", "appears twice"), (b"x" * (di.MAX_FILE_BYTES + 1), "big.csv", "limit is 10 MB")])
def test_unusable_files_are_refused_with_a_plain_reason(site, data, name, frag):
    with pytest.raises(di.ImportFileError, match=frag):
        di.import_file("Customer", data, name, di.Options())


# ============================== values ==============================
@pytest.mark.parametrize("cell,expected", [("2026-03-02", date(2026, 3, 2)), ("2026/3/2", date(2026, 3, 2)), ("02/03/2026", date(2026, 3, 2)), ("2-3-2026", date(2026, 3, 2)), ("02.03.2026", date(2026, 3, 2)),
                                           ("2 Mar 2026", date(2026, 3, 2)), ("March 2, 2026", date(2026, 3, 2)), ("2026-03-02 14:30:00", date(2026, 3, 2)), (46083, date(2026, 3, 2))])
def test_dates_in_the_formats_people_actually_use(cell, expected):
    assert di.parse_date(cell, "DMY") == expected


def test_day_first_or_month_first_is_a_choice_and_nonsense_is_refused():
    assert di.parse_date("03/04/2026", "DMY") == date(2026, 4, 3) and di.parse_date("03/04/2026", "MDY") == date(2026, 3, 4)
    for bad in ("31/02/2026", "2026-13-01", "tomorrow", "13/13/2026", "", 5, True):
        with pytest.raises(di._Bad):
            di.parse_date(bad)


@pytest.mark.parametrize("cell,expected", [("1,234.50", D("1234.50")), ("₦1,000", D("1000")), ("$ 12", D("12")), ("(100)", D("-100")), ("100-", D("-100")), (7, D("7")), (2.5, D("2.5")), ("-3", D("-3"))])
def test_numbers_with_commas_currency_signs_and_accounting_negatives(cell, expected):
    assert di._number(cell) == expected


@pytest.mark.parametrize("bad", ["abc", "1.2.3", "NaN", "Infinity", True, "1,2,3x"])
def test_bad_numbers_are_refused(bad):
    with pytest.raises(di._Bad):
        di._number(bad)


def test_cell_errors_name_the_line_the_column_and_the_reason_and_the_good_rows_still_import(site):
    groups("Retail")
    text = ("Customer Name,Customer Group,Status,Credit Limit,Tax Exempt\n"
            "Good Ltd,Retail,Active,100,yes\n"
            "Bad Group,Nowhere,Active,100,no\n"
            "Bad Status,Retail,Weird,100,no\n"
            "Bad Money,Retail,Active,lots,no\n"
            "Bad Flag,Retail,Active,100,maybe\n"
            ",Retail,Active,100,no\n")
    rep = imp("Customer", text)
    assert (rep.total, rep.created, rep.failed) == (6, 1, 5) and list(customers()) == ["Good Ltd"]
    by = {e["row"]: e for e in rep.errors}
    assert by[3]["field"] == "Customer Group" and "'Nowhere' is not an existing Customer Group" in by[3]["message"]
    assert by[4]["field"] == "Status" and "not one of: " in by[4]["message"] and "Active" in by[4]["message"]
    assert by[5]["field"] == "Credit Limit" and "'lots' is not a number" in by[5]["message"]
    assert "not yes/no" in by[6]["message"] and "Customer Name" in by[7]["message"]                                      # a missing required value: the engine's own message
    assert [r["row"] for r in rep.failed_rows] == [3, 4, 5, 6, 7] and rep.failed_rows[0]["data"]["Customer Name"] == "Bad Group"


def test_links_are_found_ignoring_case_and_by_title_and_ambiguity_is_refused(site):
    groups("Retail")
    c = new_doc("Customer", customer_name="Acme Stores").insert()
    new_doc("Customer", customer_name="Twin").insert()
    new_doc("Customer", customer_name="Twin").insert()
    rows = "Customer,Items.Description,Items.Qty,Items.Rate\n{},A,1,1\n"
    ok = [imp("Sales Order", rows.format(v)) for v in (c.name, c.name.lower(), "Acme Stores")]
    assert [r.created for r in ok] == [1, 1, 1] and {get_doc("Sales Order", r.names[0]).customer for r in ok} == {c.name}
    amb = imp("Sales Order", rows.format("Twin"))
    assert amb.failed == 1 and "matches more than one Customer by name; use the ID instead" in amb.errors[0]["message"]
    miss = imp("Sales Order", rows.format("Ghost"))
    assert "is not an existing Customer" in miss.errors[0]["message"]


def test_text_too_long_and_formula_looking_text(site):
    rep = imp("Customer", "Customer Name\n" + "x" * 300 + "\n")
    assert rep.failed == 1 and "too long: 300 characters, at most 255 allowed" in rep.errors[0]["message"]
    rep = imp("Customer", "Customer Name,Email\n=HYPERLINK(\"http://evil\"),x@y.ng\n")
    assert rep.created == 1 and customers()['=HYPERLINK("http://evil")']["email"] == "x@y.ng"                            # imported as plain text, never evaluated


# ============================== child rows (Frappe layout) ==============================
ORDERS = ("Customer,Order Date,Items.Description,Items.Qty,Items.Rate\n"
          "{c},2026-03-02,Widget,2,100\n"
          ",,Gadget,1,50\n"
          ",,Gizmo,3,10\n"
          "{c},2026-03-05,Solo,1,5\n")


def test_child_rows_sit_on_the_lines_under_their_document(site):
    c = new_doc("Customer", customer_name="Acme").insert()
    rep = imp("Sales Order", ORDERS.format(c=c.name))
    assert (rep.total, rep.created, rep.failed) == (2, 2, 0)
    first, second = (get_doc("Sales Order", n) for n in rep.names)
    assert [(r.description, r.qty, r.rate) for r in first.items] == [("Widget", 2, 100), ("Gadget", 1, 50), ("Gizmo", 3, 10)] and first.total == 280          # computed totals still compute
    assert [r.description for r in second.items] == ["Solo"] and second.order_date == date(2026, 3, 5)


def test_an_error_in_a_child_row_names_that_line_and_fails_only_its_document(site):
    c = new_doc("Customer", customer_name="Acme").insert()
    text = ORDERS.format(c=c.name).replace(",,Gadget,1,50", ",,Gadget,one,50")
    rep = imp("Sales Order", text)
    assert (rep.created, rep.failed) == (1, 1)
    e = rep.errors[0]
    assert e["row"] == 3 and e["field"] == "Items.Qty" and "'one' is not a number" in e["message"]                       # line 3 of the file, the column, the reason
    assert [r["row"] for r in rep.failed_rows] == [2, 3, 4] and rep.failed_rows[0]["error"] and not rep.failed_rows[1]["error"]       # the whole document's lines come back together


def test_a_first_line_with_only_child_cells_is_reported_not_guessed(site):
    c = new_doc("Customer", customer_name="Acme").insert()
    rep = imp("Sales Order", f",,Orphan,1,1\n{c.name},2026-03-02,Widget,1,1\n".join(["Customer,Order Date,Items.Description,Items.Qty,Items.Rate\n", ""]))
    assert rep.created == 1 and any("only child-table cells" in e["message"] and e["row"] == 2 for e in rep.errors)


def test_a_document_with_no_child_rows_is_refused_by_the_normal_rules(site):
    c = new_doc("Customer", customer_name="Acme").insert()
    rep = imp("Sales Order", f"Customer,Order Date\n{c.name},2026-03-02\n")
    assert rep.failed == 1 and "items needs at least one row" in rep.errors[0]["message"]                                                       # the DocType says items are required: the importer does not bypass that


# ============================== modes ==============================
def test_update_changes_only_the_cells_you_give_and_never_erases(site):
    groups("Retail", "Wholesale")
    new_doc("Customer", customer_name="Acme", email="old@acme.ng", customer_group="Retail", credit_limit=5).insert()
    name = customers()["Acme"]["name"]
    rep = imp("Customer", f"ID,Customer Group,Email\n{name},Wholesale,\n", mode="update")
    assert (rep.updated, rep.created, rep.failed) == (1, 0, 0)
    c = customers()["Acme"]
    assert c["customer_group"] == "Wholesale" and c["email"] == "old@acme.ng" and c["credit_limit"] == 5                  # the blank Email did NOT erase the old one


def test_update_needs_an_id_or_a_unique_match_and_the_document_must_exist(site):
    new_doc("Customer", customer_name="Acme").insert()
    r = imp("Customer", "Customer Name,Status\nAcme,Active\n", mode="update")
    assert r.failed == 1 and "give the ID column" in r.errors[0]["message"]
    r = imp("Customer", "ID,Status\nCUST-9999,Active\n", mode="update")
    assert r.failed == 1 and "no Customer to update with ID 'CUST-9999'" in r.errors[0]["message"]
    with pytest.raises(ValidationError, match="--match must be a unique field"):
        imp("Customer", "ID,Status\nCUST-0001,Active\n", mode="update", match="status")


def test_match_by_a_unique_field_for_documents_named_by_it(site):
    new_doc("Customer Group", group_name="Retail", description="old").insert()
    rep = imp("Customer Group", "Group Name,Description\nRetail,new text\nWholesale,brand new\n", mode="upsert", match="group_name")
    assert (rep.created, rep.updated, rep.failed) == (1, 1, 0)
    assert get_doc("Customer Group", "Retail").description == "new text" and get_doc("Customer Group", "Wholesale").description == "brand new"


def test_upsert_updates_what_exists_and_creates_what_does_not(site):
    c = new_doc("Customer", customer_name="Acme", status="Active").insert()
    rep = imp("Customer", f"ID,Customer Name,Status\n{c.name},Acme,Inactive\n,Brand New,Active\n", mode="upsert")
    assert (rep.created, rep.updated, rep.failed) == (1, 1, 0) and customers()["Acme"]["status"] == "Inactive" and "Brand New" in customers()


def test_submitted_documents_cannot_be_updated_and_replacing_child_rows_works_on_drafts(site):
    c = new_doc("Customer", customer_name="Acme").insert()
    so = imp("Sales Order", f"Customer,Items.Description,Items.Qty,Items.Rate\n{c.name},Old,1,1\n").names[0]
    rep = imp("Sales Order", f"ID,Items.Description,Items.Qty,Items.Rate\n{so},New A,1,10\n,New B,2,20\n", mode="update")
    assert rep.updated == 1 and [r.description for r in get_doc("Sales Order", so).items] == ["New A", "New B"]                # the rows you give REPLACE the table
    get_doc("Sales Order", so).submit()
    rep = imp("Sales Order", f"ID,Order Date\n{so},2026-04-01\n", mode="update")
    assert rep.failed == 1 and f"{so} is submitted and can no longer be changed" in rep.errors[0]["message"]


def test_insert_of_an_id_is_refused_unless_you_say_to_keep_names_and_only_a_system_manager_may(site):
    r = imp("Customer", "ID,Customer Name\nOLD-0001,Migrated\n")
    assert r.created == 1 and customers()["Migrated"]["name"].startswith("CUST-")                                      # an ID on insert is ignored: the series decides
    r = imp("Customer", "ID,Customer Name\nOLD-0002,Kept\n", keep_names=True)
    assert r.created == 1 and customers()["Kept"]["name"] == "OLD-0002"                                                 # migration: the original ID survives
    r = imp("Customer", "ID,Customer Name\nOLD-0002,Again\n", keep_names=True)
    assert r.failed == 1 and "already exists" in r.errors[0]["message"].lower()
    with session_as(Session("clerk", frozenset({"Sales Manager"}))):
        with pytest.raises(PermissionDenied, match="Only a System Manager"):
            imp("Customer", "ID,Customer Name\nOLD-0003,X\n", keep_names=True)


def test_submit_option_submits_what_it_creates(site):
    c = new_doc("Customer", customer_name="Acme").insert()
    rep = imp("Sales Order", f"Customer,Items.Description,Items.Qty,Items.Rate\n{c.name},A,1,1\n", submit=True)
    assert rep.created == 1 and get_doc("Sales Order", rep.names[0]).docstatus == 1
    with pytest.raises(ValidationError, match="cannot be submitted"):
        imp("Customer", "Customer Name\nX\n", submit=True)


# ============================== dry run and atomic ==============================
def test_a_dry_run_reports_exactly_what_would_happen_and_saves_nothing(site):
    groups("Retail")
    before = db_counts()
    dry = imp("Customer", CSV_CUSTOMERS, dry_run=True)
    assert dry.dry_run and (dry.created, dry.failed) == (2, 0) and dry.rolled_back and len(dry.names) == 2
    assert db_counts() == before and customers() == {}                                                                  # nothing saved, no series number used
    real = imp("Customer", CSV_CUSTOMERS)
    assert real.names == dry.names                                                                                      # the real run gets the very same IDs the check promised
    assert db_counts()["Customer"] == 2


def db_counts():
    from sqlalchemy import func, select
    from velora.db.tables import get_table
    out = {}
    with db.transaction() as c:
        for dt in ("Customer", "Customer Contact", "Customer Group"):
            out[dt] = c.execute(select(func.count()).select_from(get_table(dt))).scalar()
    return out


def test_a_dry_run_finds_the_same_problems_the_real_run_would(site):
    groups("Retail")
    new_doc("Customer Group", group_name="Dup").insert() if False else None
    text = "Customer Name,Customer Group\nOk,Retail\nBad,Nowhere\n"
    dry, real = imp("Customer", text, dry_run=True), imp("Customer", text)
    assert (dry.created, dry.failed, dry.errors) == (real.created, real.failed, real.errors)


def test_a_duplicate_of_a_unique_value_is_caught_in_the_dry_run_including_inside_the_file(site):
    new_doc("Customer Group", group_name="Retail").insert()
    r = imp("Customer Group", "Group Name\nRetail\nFresh\nFresh\n", dry_run=True)
    assert (r.created, r.failed) == (1, 2) and all("already exists" in e["message"].lower() for e in r.errors)           # Retail exists; the second Fresh clashes with the first


def test_all_or_nothing_imports_nothing_when_anything_fails(site):
    groups("Retail")
    text = "Customer Name,Customer Group\nGood,Retail\nBad,Nowhere\nAlsoGood,Retail\n"
    rep = imp("Customer", text, atomic=True)
    assert rep.failed == 1 and rep.created == 0 and rep.rolled_back and customers() == {}
    assert imp("Customer", text).created == 2 and set(customers()) == {"Good", "AlsoGood"}                              # without the flag the good ones go in
    assert imp("Customer", "Customer Name\nFine1\nFine2\n", atomic=True).created == 2                                    # all fine: all in


def test_a_bad_row_never_leaves_half_a_document_behind(site):
    c = new_doc("Customer", customer_name="Acme").insert()
    imp("Sales Order", f"Customer,Items.Description,Items.Qty,Items.Rate\n{c.name},A,1,1\n,B,1,\n")                       # the second child row has no rate (required)
    from sqlalchemy import func, select
    from velora.db.tables import get_table
    with db.transaction() as conn:
        assert conn.execute(select(func.count()).select_from(get_table("Sales Order"))).scalar() == 0
        assert conn.execute(select(func.count()).select_from(get_table("Sales Order Item"))).scalar() == 0


# ============================== permissions and limits ==============================
def test_import_goes_through_the_normal_permissions(site):
    with session_as(Session("nobody", frozenset({"Stranger"}))):
        with pytest.raises(PermissionDenied):
            imp("Customer", "Customer Name\nX\n")
        with pytest.raises(PermissionDenied):
            di.template("Customer")
        with pytest.raises(PermissionDenied):
            di.export_data("Customer", "json")
    with pytest.raises(ValidationError, match="child table"):
        imp("Customer Contact", "Contact Name\nX\n")


def test_options_and_size_limits_are_checked(site):
    for kw, frag in (({"mode": "delete"}, "mode must be one of"), ({"date_format": "XYZ"}, "date format must be one of"), ({"max_rows": 1}, "at most 1 can be imported")):
        with pytest.raises(ValidationError, match=frag):
            imp("Customer", "Customer Name\nA\nB\n", **kw)


def test_read_only_and_unknown_columns(site):
    c = new_doc("Customer", customer_name="Acme").insert()
    rep = imp("Sales Order", f"Customer,Total,Mystery,Items.Description,Items.Qty,Items.Rate\n{c.name},999,x,A,1,1\n")
    assert rep.unknown_columns == ["Total", "Mystery"] and rep.failed == 0 and get_doc("Sales Order", rep.names[0]).total == 1      # the calculated Total is recomputed, never taken from the file


# ============================== template ==============================
def test_the_template_has_the_headings_and_explains_itself(site):
    data, name, ctype = di.template("Sales Order", "xlsx")
    assert name == "Sales_Order_import_template.xlsx" and ctype.endswith("spreadsheetml.sheet")
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Import", "Instructions"]
    heads = [c.value for c in wb["Import"][1]]
    assert heads == ["ID", "Customer *", "Order Date", "Items.Description *", "Items.Qty *", "Items.Rate *"]            # required ones are starred; calculated ones are absent
    text = " ".join(str(c.value) for row in wb["Instructions"].iter_rows() for c in row if c.value)
    assert "UNDER it" in text and "Check file" in text and "an existing Customer" in text and "Table.Field" in text
    csv_data, name, _ = di.template("Customer", "csv")
    assert name == "Customer_import_template.csv" and csv_data.decode("utf-8-sig").strip() == "ID,Customer Name *,Email Address,Customer Group,Status,Credit Limit,Tax Exempt,Contacts.Contact Name *,Contacts.Email,Contacts.Phone"
    sel = {r[0].value: r[3].value for r in wb["Instructions"].iter_rows(min_row=1) if r[0].value}
    assert di.template("Customer", "xlsx")[0] and sel
    with pytest.raises(ValidationError, match="xlsx or csv"):
        di.template("Customer", "pdf")


def test_a_filled_in_template_imports_without_any_change(site):
    data, _, _ = di.template("Customer", "csv")
    filled = data.decode("utf-8-sig").strip() + "\n,Acme,a@b.ng,,Active,100,no,Ada,ada@b.ng,0803\n"
    rep = imp("Customer", filled)
    assert rep.created == 1 and rep.failed == 0 and [c.contact_name for c in get_doc("Customer", rep.names[0]).contacts] == ["Ada"]


# ============================== export and migration ==============================
def seed_customers():
    groups("Retail")
    for n, st, lim in (("Acme", "Active", 1500), ("Bola", "Blocked", 0)):
        d = new_doc("Customer", customer_name=n, status=st, credit_limit=lim, customer_group="Retail", tax_exempt=1)
        d.append("contacts", {"contact_name": f"{n} Contact", "phone": "0803"})
        d.append("contacts", {"contact_name": f"{n} Second", "email": "x@y.ng"})
        d.insert()


@pytest.mark.parametrize("fmt", ["json", "csv", "xlsx"])
def test_what_is_exported_imports_back_exactly_in_every_format(site, fmt):
    seed_customers()
    data, name, ctype, n = di.export_data("Customer", fmt)
    assert n == 2 and name.endswith("." + fmt)
    before = {k: {kk: vv for kk, vv in v.items()} for k, v in customers().items()}
    contacts = {d["customer_name"]: [(c.contact_name, c.email, c.phone) for c in get_doc("Customer", d["name"]).contacts] for d in before.values()}
    with db.transaction() as c:                                                                                         # a different company: start empty
        c.exec_driver_sql("DELETE FROM tab_customer_contact")
        c.exec_driver_sql("DELETE FROM tab_customer")
    rep = di.import_file("Customer", data, f"x.{fmt}", di.Options(keep_names=True))
    assert (rep.created, rep.failed) == (2, 0), rep.errors
    after = customers()
    assert {k: {kk: vv for kk, vv in v.items()} for k, v in after.items()} == before                                    # same IDs, same values
    assert {d["customer_name"]: [(c.contact_name, c.email, c.phone) for c in get_doc("Customer", d["name"]).contacts] for d in after.values()} == contacts   # and the same child rows in order


def test_json_export_is_self_describing_and_keeps_money_exact(site):
    new_doc("Customer", customer_name="Acme", credit_limit=D("1234567.891234")).insert()
    data = json.loads(di.export_data("Customer", "json")[0])
    assert data["doctype"] == "Customer" and data["count"] == 1 and data["data"][0]["credit_limit"] == "1234567.891234" and data["data"][0]["contacts"] == [] and data["data"][0]["docstatus"] == 0


def test_csv_export_lays_children_out_on_continuation_lines_and_protects_formulas(site):
    new_doc("Customer", customer_name="=cmd|' /C calc'!A0", credit_limit=1).insert()
    seed_customers()
    text = di.export_data("Customer", "csv")[0].decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][0] == "ID" and "Contacts.Contact Name" in rows[0]
    ci = rows[0].index("Customer Name")
    assert any(r[ci] == "'=cmd|' /C calc'!A0" for r in rows)                                                            # text starting with = is defanged in the file ...
    imp_rep = di.import_file("Customer", text.encode(), "x.csv", di.Options())
    assert "=cmd|' /C calc'!A0" in {c["customer_name"] for c in get_list("Customer", fields=["customer_name"], ignore_permissions=True)} and imp_rep.failed == 0   # ... and restored on the way back in
    blank_parent = [r for r in rows[1:] if r[0] == "" and r[ci] == ""]
    assert len(blank_parent) == 2                                                                                       # each seeded customer's SECOND contact sits under it
    wb = load_workbook(io.BytesIO(di.export_data("Customer", "xlsx")[0]))
    assert all(c.data_type != "f" for row in wb["Import"].iter_rows() for c in row)                                     # never a live formula in Excel either


def test_export_filters_limits_and_the_audit_log(site):
    seed_customers()
    data, _, _, n = di.export_data("Customer", "json", filters=[["status", "=", "Active"]])
    assert n == 1 and json.loads(data)["data"][0]["customer_name"] == "Acme"
    assert di.export_data("Customer", "json", limit=1)[3] == 1
    with pytest.raises(ValidationError, match="json, csv or xlsx"):
        di.export_data("Customer", "pdf")
    with pytest.raises(ValidationError):
        di.export_data("Customer", "json", filters=[["nope", "=", 1]])
    from velora.db.system import export_log
    from sqlalchemy import select
    with db.transaction() as c:
        rows = c.execute(select(export_log.c.scope, export_log.c.ref_doctype, export_log.c.row_count)).all()
    assert ("export-json", "Customer", 1) in rows
    imp("Customer", "Customer Name\nLogged\n")
    with db.transaction() as c:
        assert any(r[0] == "import-insert" and r[1] == "Customer" and r[2] == 1 for r in c.execute(select(export_log.c.scope, export_log.c.ref_doctype, export_log.c.row_count)).all())
    imp("Customer", "Customer Name\nChecked\n", dry_run=True)
    with db.transaction() as c:
        assert c.execute(select(export_log.c.name).where(export_log.c.row_count == 1, export_log.c.scope == "import-insert")).all().__len__() == 1       # a dry run is not logged as an import


def test_the_error_file_can_be_corrected_and_imported(site):
    groups("Retail")
    text = "Customer Name,Customer Group\nGood,Retail\nFixable,Retial\n"
    rep = imp("Customer", text)
    assert rep.failed == 1
    err = di.errors_csv(rep)
    rows = list(csv.reader(io.StringIO(err)))
    assert rows[0] == ["Customer Name", "Customer Group", "Error"] and rows[1][:2] == ["Fixable", "Retial"] and "not an existing Customer Group" in rows[1][2]
    fixed = err.replace("Retial", "Retail")
    again = imp("Customer", fixed)                                                                                      # the "Error" column matches nothing and is simply ignored
    assert again.created == 1 and again.unknown_columns == ["Error"] and set(customers()) == {"Good", "Fixable"}


# ============================== the API ==============================
@pytest.fixture
def api(site):
    return TestClient(create_app(auto_init=False))


def post(api, path, data, filename="x.csv", **params):
    return api.post(path, content=data if isinstance(data, bytes) else data.encode(), headers={**ADMIN, "X-Filename": filename, "Content-Type": "application/octet-stream"}, params=params)


def test_the_api_checks_then_imports_and_returns_the_error_file(api, site):
    groups("Retail")
    text = "Customer Name,Customer Group\nGood,Retail\nBad,Nowhere\n"
    chk = post(api, "/api/data-import/Customer", text, dry_run=1).json()["data"]
    assert chk["dry_run"] and chk["created"] == 1 and chk["failed"] == 1 and not chk["ok"] and chk["errors"][0]["row"] == 3 and customers() == {}
    done = post(api, "/api/data-import/Customer", text).json()["data"]
    assert done["created"] == 1 and set(customers()) == {"Good"}
    r = api.post("/api/data-import/errors-csv", json={"failed_rows": done["failed_rows"]}, headers=ADMIN)
    assert r.status_code == 200 and r.headers["content-disposition"].endswith('import_errors.csv"') and "not an existing Customer Group" in r.content.decode("utf-8-sig")
    assert api.post("/api/data-import/errors-csv", json={"failed_rows": "x"}, headers=ADMIN).status_code == 422


def test_the_api_serves_templates_and_exports_as_downloads(api, site):
    seed_customers()
    t = api.get("/api/data-import/Customer/template?format=csv", headers=ADMIN)
    assert t.status_code == 200 and "attachment" in t.headers["content-disposition"] and t.content.startswith(b"\xef\xbb\xbfID,Customer Name")
    x = api.get("/api/data-import/Customer/template", headers=ADMIN)
    assert x.content[:2] == b"PK"
    e = api.get("/api/data-export/Customer?format=json&filters=" + json.dumps([["status", "=", "Active"]]), headers=ADMIN)
    assert e.status_code == 200 and json.loads(e.content)["count"] == 1
    assert api.get("/api/data-export/Customer?format=csv&limit=1", headers=ADMIN).status_code == 200
    assert api.get("/api/data-export/Customer?filters=nope", headers=ADMIN).status_code == 422
    assert api.get("/api/data-export/Customer?format=pdf", headers=ADMIN).status_code == 422


def test_the_api_refuses_what_it_should(api, site):
    assert api.post("/api/data-import/Customer", content=b"Customer Name\nX\n", headers={"X-Filename": "x.csv"}).status_code in (401, 403)
    nobody = {"X-Velora-User": "nobody", "X-Velora-Roles": "Stranger", "X-Filename": "x.csv"}
    assert api.post("/api/data-import/Customer", content=b"Customer Name\nX\n", headers=nobody).status_code == 403
    assert api.get("/api/data-export/Customer", headers=nobody).status_code == 403
    assert api.get("/api/data-import/Customer/template", headers=nobody).status_code == 403
    r = post(api, "/api/data-import/Customer", b"", "x.csv")
    assert r.status_code == 422 and "empty" in r.json()["message"]
    assert post(api, "/api/data-import/Customer", b"x", "x.exe").status_code == 422
    assert post(api, "/api/data-import/Nope", b"a\n1\n", "x.csv").status_code == 404
    big = "Customer Name\n" + "\n".join(f"C{i}" for i in range(di.API_MAX_ROWS + 1))
    r = post(api, "/api/data-import/Customer", big)
    assert r.status_code == 422 and "velora import-data" in r.json()["message"]                                          # big loads are for the server's command line


def test_api_options_are_parsed(api, site):
    c = new_doc("Customer", customer_name="Acme").insert()
    post(api, "/api/data-import/Sales Order", f"Customer,Order Date,Items.Description,Items.Qty,Items.Rate\n{c.name},03/04/2026,A,1,1\n", submit="1", date_format="MDY")
    so = get_list("Sales Order", fields=["name", "order_date", "docstatus"], ignore_permissions=True)[0]
    assert so["docstatus"] == 1 and so["order_date"] == date(2026, 3, 4)                                                 # month first, and submitted
    r = post(api, "/api/data-import/Customer", "ID,Customer Name\nKEEP-1,K\n", keep_names="1", atomic="yes")
    assert r.json()["data"]["created"] == 1 and "KEEP-1" in {x["name"] for x in get_list("Customer", fields=["name"], ignore_permissions=True)}


# ============================== the command line ==============================
def test_the_command_line_imports_exports_and_writes_templates(tmp_path):
    """Run the real command in its own process, as a person would (so no other test's database can be in the way)."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "VELORA_DB_URL": f"sqlite:///{tmp_path / 'cli.db'}", "VELORA_APPS": "velora_demo", "PYTHONPATH": f"{root}{os.pathsep}{root / 'apps' / 'velora_demo'}"}
    env.pop("VELORA_WORKSPACE", None)

    def cli(*args):
        r = subprocess.run([sys.executable, "-m", "velora.cli", *args], capture_output=True, text=True, cwd=tmp_path, env=env, timeout=120)
        return r.returncode, r.stdout, r.stderr

    assert cli("migrate")[0] == 0
    f = tmp_path / "c.csv"
    f.write_text("Customer Name,Status\nAcme,Active\nBad,Weird\n")
    code, out, _ = cli("import-data", "Customer", str(f), "--dry-run")
    assert code == 1 and "DRY RUN (nothing was saved): 2 document(s) in the file. Would create 1" in out and "line 3 Status:" in out and "not one of" in out
    code, out, _ = cli("export-data", "Customer", "--out", str(tmp_path / "none.json"))
    assert code == 0 and json.loads((tmp_path / "none.json").read_text())["count"] == 0                                    # the dry run saved nothing
    rep = tmp_path / "failed.csv"
    code, out, _ = cli("import-data", "Customer", str(f), "--report", str(rep))
    assert code == 1 and "Created 1" in out and f"in {rep}" in out and "Weird" in rep.read_text(encoding="utf-8-sig")
    code, out, _ = cli("export-data", "Customer", "--out", str(tmp_path / "out.json"))
    assert code == 0 and "Exported 1 Customer document(s)" in out and "--keep-names" in out and json.loads((tmp_path / "out.json").read_text())["count"] == 1
    code, out, _ = cli("import-template", "Customer", "--format", "csv", "--out", str(tmp_path / "t.csv"))
    assert code == 0 and (tmp_path / "t.csv").read_bytes().startswith(b"\xef\xbb\xbfID,Customer Name") and "--dry-run" in out
    assert "No such file" in cli("import-data", "Customer", str(tmp_path / "nope.csv"))[2]
    assert "--filters must be JSON" in cli("export-data", "Customer", "--filters", "nope")[2]
    code, _, err = cli("import-data", "Customer", str(tmp_path / "t.csv"))
    assert code != 0 and "no data rows" in err
    code, out, _ = cli("import-data", "Customer", str(f), "--mode", "upsert", "--match", "customer_name")
    assert code != 0 or "--match" in out


# ============================== guarantees that need a sharper test ==============================
def test_a_failure_AFTER_the_document_was_written_leaves_nothing_behind(site, monkeypatch):
    """The savepoint's job: the order below is inserted, then its submit fails. The draft and its rows must vanish, and the next order must still go in."""
    from velora.document.document import Document
    boom = ValidationError("Submit refused by a rule")

    def refuse(self):
        if self.items and self.items[0].description == "Boom":
            raise boom
    monkeypatch.setattr(Document, "on_submit", refuse, raising=False)
    c = new_doc("Customer", customer_name="Acme").insert()
    rep = imp("Sales Order", f"Customer,Items.Description,Items.Qty,Items.Rate\n{c.name},Boom,1,1\n,Extra,1,1\n{c.name},Fine,1,1\n", submit=True)
    assert (rep.created, rep.failed) == (1, 1) and "Submit refused by a rule" in rep.errors[0]["message"]
    from sqlalchemy import func, select
    from velora.db.tables import get_table
    with db.transaction() as conn:
        assert conn.execute(select(func.count()).select_from(get_table("Sales Order"))).scalar() == 1               # only "Fine": no orphan draft for "Boom"
        assert sorted(conn.execute(select(get_table("Sales Order Item").c.description)).scalars()) == ["Fine"]     # and none of its rows


def test_atomic_stops_at_the_first_failure_and_reports_it(site):
    groups("Retail")
    rep = imp("Customer", "Customer Name,Customer Group\nA,Nowhere\nB,Retail\nC,Nowhere\n", atomic=True)
    assert (rep.created, rep.failed, rep.rolled_back) == (0, 1, True) and rep.errors[0]["row"] == 2 and customers() == {}


def test_a_blank_value_is_nothing_whatever_the_field_type(site):
    from velora.meta.registry import registry
    ctx = di.Ctx(di.Options())
    for f in registry.get("Customer").fields:
        if f.has_column and not f.is_layout:
            assert di.parse_value(f, None, ctx) is None and di.parse_value(f, "   ", ctx) is None, f.fieldname            # never the text "None", never a zero


def test_exporting_needs_the_export_permission_not_just_read(site, monkeypatch):
    seed_customers()
    real = di.check_permission
    monkeypatch.setattr(di, "check_permission", lambda meta, ptype, *a, **k: (_ for _ in ()).throw(PermissionDenied("no export")) if ptype == "export" else real(meta, ptype, *a, **k))
    for fmt in ("json", "csv", "xlsx"):
        with pytest.raises(PermissionDenied, match="no export"):
            di.export_data("Customer", fmt)
    assert get_list("Customer", fields=["name"])                                                                        # reading is still fine: only the export is refused
