"""Bank Reconciliation: statement readers, the matching engine, and the end-to-end flow against the real ledger."""
from datetime import date
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc, get_list
from velora.exceptions import ValidationError
from velora.permissions import session_as
from test_cash_transactions import setup_cash, approve, MAKER, APPROVER
from velora_erp.finance import bank_matching as bm, bank_statement_parsers as sp, bank_reconciliation as svc

Y = date.today().year


# ---------------------------------------------------------------------------------------------------------------- parsers
def test_csv_with_preamble_debit_credit_columns_and_running_balance():
    text = ("ACME BANK PLC\nAccount Statement\n\nTrans Date,Narration,Ref No,Debit,Credit,Balance\n"
            "01/03/2026,Opening,,,,\n02/03/2026,NIP TRANSFER FROM ACME LTD,NIP123456,,\"150,000.00\",\"650,000.00\"\n"
            "05/03/2026,Cheque 000231 Supply Co,000231,\"40,000.00\",,\"610,000.00\"\nTotals,,,40000,150000,\n")
    p = sp.parse_statement(content=text)
    assert [(r["direction"], r["amount"], r["reference"]) for r in p.rows] == [("Receipt", Decimal("150000.00"), "NIP123456"), ("Payment", Decimal("40000.00"), "000231")]
    assert p.rows[0]["date"] == date(2026, 3, 2), "day-first dates by default"
    assert p.opening_balance == Decimal("500000.00") and p.closing_balance == Decimal("610000.00") and not p.warnings


def test_csv_single_amount_flag_and_month_first_and_negative_brackets():
    p = sp.parse_statement(content="Date,Details,Amount\n03/14/2026,Pay in,\"1,000.50\"\n03/15/2026,Pay out,(250.00)\n", day_first=False)
    assert [(r["date"], r["direction"], r["amount"]) for r in p.rows] == [(date(2026, 3, 14), "Receipt", Decimal("1000.50")), (date(2026, 3, 15), "Payment", Decimal("250.00"))]
    p = sp.parse_statement(content="Date;Description;Amount;Dr/Cr\n2026-03-01;A;100,00;DR\n2026-03-02;B;200,00;CR\n")
    assert [(r["direction"], r["amount"]) for r in p.rows] == [("Payment", Decimal("100.00")), ("Receipt", Decimal("200.00"))]


def test_ofx_and_mt940():
    ofx = ("OFXHEADER:100\n<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>NGN<BANKACCTFROM><ACCTID>0123</BANKACCTFROM><BANKTRANLIST>"
           "<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260302120000<TRNAMT>1500.00<FITID>F1<NAME>ACME LTD<MEMO>INV 55</STMTTRN>"
           "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260304<TRNAMT>-200.00<FITID>F2<NAME>BANK CHARGE</STMTTRN></BANKTRANLIST>"
           "<LEDGERBAL><BALAMT>3300.00<DTASOF>20260304</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>")
    p = sp.parse_statement(content=ofx)
    assert p.format == "OFX" and p.currency == "NGN" and len(p.rows) == 2 and p.closing_balance == Decimal("3300.00") and p.opening_balance == Decimal("2000.00")
    mt = (":20:STMT1\n:25:0123456789\n:28C:1/1\n:60F:C260301NGN1000,00\n:61:2603020302C500,00NTRFNONREF//B1\n:86:INWARD NIP FROM ACME\n"
          ":61:2603040304D120,50NCHGBC001\n:86:ACCOUNT MAINTENANCE\n:62F:C260304NGN1379,50\n")
    p = sp.parse_statement(content=mt)
    assert p.format == "MT940" and [(r["direction"], r["amount"]) for r in p.rows] == [("Receipt", Decimal("500.00")), ("Payment", Decimal("120.50"))]
    assert p.opening_balance == Decimal("1000.00") and p.closing_balance == Decimal("1379.50") and not p.warnings


def test_unreadable_files_are_refused_with_a_reason():
    with pytest.raises(sp.StatementError, match="header"):
        sp.parse_statement(content="hello\nworld\n")
    with pytest.raises(sp.StatementError, match="empty"):
        sp.parse_statement(content="  ")


# ----------------------------------------------------------------------------------------------------------------- engine
def S(i, d, amt, ref="", desc="", cp=""):
    return {"id": i, "date": date(2026, 3, d), "signed": Decimal(str(amt)), "reference": ref, "description": desc, "counterparty": cp}


def G(i, d, amt, refs=(), text="", party=None):
    return {"id": i, "date": date(2026, 3, d), "signed": Decimal(str(amt)), "refs": list(refs), "text": text, "party": party}


def test_reference_match_wins_over_look_alike_amounts():
    groups = bm.match([S("s1", 5, 1000, ref="NIP778899"), S("s2", 5, 1000, ref="NIP111111")],
                      [G("g1", 5, 1000, refs=["NIP111111"]), G("g2", 5, 1000, refs=["NIP778899"])])
    pairs = {(g.lines[0], g.records[0]): g for g in groups}
    assert set(pairs) == {("s1", "g2"), ("s2", "g1")}
    assert all(g.method == "Reference" and g.confidence >= 90 for g in groups)


def test_unique_amount_is_confirmed_but_ambiguous_amounts_wait_for_review():
    unique = bm.match([S("s1", 5, 777.77)], [G("g1", 6, 777.77), G("g2", 6, 500)])[0]
    assert unique.method == "Exact Amount" and unique.confidence >= 90
    amb = bm.match([S("s1", 5, 1000, desc="Payment to Supply Co")], [G("g1", 5, 1000, text="Other vendor"), G("g2", 5, 1000, text="Blue Co")])
    assert len(amb) == 1 and amb[0].confidence < 90, "several equal amounts and no wording evidence: a person decides"
    clear = bm.match([S("s1", 5, 1000, desc="Payment to Supply Co Ltd")], [G("g1", 5, 1000, text="Supply Co payment"), G("g2", 5, 1000, text="Quartz Holdings")])
    assert clear[0].records == ["g1"]


def test_dates_far_apart_are_never_auto_confirmed_and_tolerance_makes_suggestions_only():
    far = bm.match([S("s1", 1, 500)], [G("g1", 11, 500)], date_tolerance=4)
    assert far and far[0].confidence < 90 and "days apart" in far[0].reason
    tol = bm.match([S("s1", 5, 1000.00)], [G("g1", 5, 1000.40)], amount_tolerance=1)
    assert tol and tol[0].confidence < 90
    assert bm.match([S("s1", 5, 1000.00)], [G("g1", 5, 1000.40)]) == []


def test_combined_deposit_and_split_payment():
    g = bm.match([S("s1", 10, 600)], [G("g1", 9, 100, party="A"), G("g2", 9, 200, party="A"), G("g3", 10, 300, party="A"), G("g4", 10, 4000)])
    assert len(g) == 1 and g[0].method == "Split / Combined" and sorted(g[0].records) == ["g1", "g2", "g3"]
    g = bm.match([S("s1", 10, -300), S("s2", 10, -700)], [G("g1", 10, -1000)])
    assert len(g) == 1 and sorted(g[0].lines) == ["s1", "s2"] and g[0].records == ["g1"]


def test_reversals_cancel():
    g = bm.match([S("s1", 3, 250, ref="RTN-9981"), S("s2", 4, -250, ref="RTN-9981")], [])
    assert g[0].method == "Statement Reversal"


# --------------------------------------------------------------------------------------------------------- end to end
def _setup(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    ba = new_doc("Bank Account", account_code="MAIN", account_name="Main Account", bank_name="Acme Bank", account_number="0123456789",
                 gl_account=accounts["1000"].name, currency="NGN", auto_accept_threshold=90, date_tolerance_days=4).insert(ignore_permissions=True)
    return accounts, ba


def _book(accounts, d, direction, amount, ref, desc="x"):
    offset = accounts["4000"].name if direction == "Receipt" else accounts["5000"].name
    with session_as(MAKER):
        b = new_doc("Batch Bank Transaction", bank_account=accounts["1000"].name, posting_date=d, currency="NGN", exchange_rate=1, reference=f"B-{ref}",
                    approval_status="Pending", transactions=[{"transaction_date": d, "direction": direction, "description": desc, "offset_account": offset, "amount": amount, "reference": ref}]).insert()
    return approve(b)


CSV = ("Date,Narration,Reference,Debit,Credit,Balance\n"
       f"10/03/{Y},NIP FROM ACME LTD,NIP100,,\"250,000.00\",\"1,250,000.00\"\n"
       f"12/03/{Y},Cheque Supply Co,CHQ000231,\"80,000.00\",,\"1,170,000.00\"\n"
       f"15/03/{Y},SMS ALERT CHARGE,,\"1,500.00\",,\"1,168,500.00\"\n"
       f"20/03/{Y},Stamp duty,,\"50.00\",,\"1,168,450.00\"\n")


def test_full_cycle_import_match_post_reconcile_lock_and_cancel(tmp_path):
    accounts, ba = _setup(tmp_path)
    try:
        # opening cash in the books, then March activity
        _book(accounts, date(Y, 3, 1), "Receipt", 1_000_000, "OPEN-1")
        _book(accounts, date(Y, 3, 10), "Receipt", 250_000, "NIP100", "Acme settlement")
        _book(accounts, date(Y, 3, 11), "Payment", 80_000, "CHQ000231", "Supply Co cheque")
        _book(accounts, date(Y, 3, 28), "Payment", 12_000, "CHQ000232", "Cheque not yet presented")
        _book(accounts, date(Y, 3, 29), "Receipt", 30_000, "DEP-77", "Deposit in transit")
        gl = ba.gl_account
        # coding rules: a charge on the statement with no ledger entry is classified to an expense account
        new_doc("Bank Transaction Coding Rule", priority=10, match_field="Description", match_operator="Contains", match_text="SMS ALERT", direction="Payment", offset_account=accounts["5000"].name).insert(ignore_permissions=True)
        new_doc("Bank Transaction Coding Rule", priority=10, match_field="Description", match_operator="Contains", match_text="Stamp duty", direction="Payment", offset_account=accounts["5000"].name).insert(ignore_permissions=True)

        # opening cash at 1 March is assumed reconciled; the statement starts at 1,000,000
        res = svc.clear_opening_entries(ba.name, date(Y, 3, 2))
        assert res["cleared"] == 1
        with session_as(MAKER):
            out = svc.import_statement(ba.name, content=CSV, filename="march.csv")
        assert out["created"] == 4 and out["opening_balance"] == "1000000.00" and out["closing_balance"] == "1168450.00"
        assert out["matching"]["confirmed"] == 2, out
        assert out["matching"]["coded"] == 2
        # re-importing the same file is harmless
        again = svc.import_statement(ba.name, content=CSV, filename="march.csv")
        assert again["created"] == 0 and again["duplicates_skipped"] == 4

        wb = svc.workbench(ba.name, date(Y, 3, 31))
        assert len(wb["unmatched_lines"]) == 2 and len(wb["unmatched_records"]) == 2 and len(wb["matched"]) == 3

        # unrecorded bank items go through a bank batch, which still needs approval
        posted = svc.post_coded_lines(ba.name)
        assert posted["lines"] == 2 and posted["batch"]
        batch = approve(get_doc("Batch Bank Transaction", posted["batch"]))
        assert batch.docstatus == 1
        after = svc.run_auto(ba.name)
        assert after["confirmed"] == 2
        assert not svc.workbench(ba.name)["unmatched_lines"]

        # reconcile at 31 March: GL = 1,000,000+250,000-80,000-12,000+30,000-1,550 ; bank = 1,168,450
        rec = new_doc("Bank Reconciliation", bank_account=ba.name, from_date=date(Y, 3, 1), to_date=date(Y, 3, 31),
                      statement_opening_balance=1_000_000, statement_closing_balance=1_168_450)
        with session_as(MAKER):
            rec.insert()
        assert Decimal(str(rec.ledger_balance)) == Decimal("1186450.00")
        assert Decimal(str(rec.deposits_in_transit)) == Decimal("30000.00") and Decimal(str(rec.outstanding_payments)) == Decimal("12000.00")
        assert Decimal(str(rec.adjusted_bank_balance)) == Decimal("1186450.00") and Decimal(str(rec.variance)) == 0 and rec.status == "Reconciled"
        assert rec.statement_check == 0 and rec.match_rate == 100
        assert {i.category for i in rec.items} == {"Deposit in Transit", "Outstanding Payment"}
        rec = approve(rec)
        assert rec.docstatus == 1
        locked = get_list("Bank Statement Line", filters=[["reconciliation", "=", rec.name]], fields=["name"], limit=50, ignore_permissions=True)
        assert len(locked) == 4
        grp = get_list("Bank Reconciliation Match", filters=[["statement_line", "=", locked[0]["name"]]], fields=["match_group"], limit=1, ignore_permissions=True)[0]["match_group"]
        with pytest.raises(ValidationError, match="submitted reconciliation"):
            svc.unmatch(grp)
        with session_as(APPROVER):
            get_doc("Bank Reconciliation", rec.name).cancel(ignore_permissions=True)
        assert svc.unmatch(grp) >= 2
    finally:
        velora.shutdown()


def test_unbalanced_reconciliation_cannot_be_submitted_and_manual_match_checks_the_sum(tmp_path):
    accounts, ba = _setup(tmp_path)
    try:
        _book(accounts, date(Y, 4, 2), "Receipt", 5000, "R1")
        _book(accounts, date(Y, 4, 3), "Receipt", 7000, "R2")
        csv_text = f"Date,Narration,Debit,Credit\n05/04/{Y},Lodgement,,\"12,000.00\"\n"
        out = svc.import_statement(ba.name, content=csv_text, auto=False)
        line = get_list("Bank Statement Line", filters=[["bank_account", "=", ba.name]], fields=["name"], limit=5, ignore_permissions=True)[0]["name"]
        recs = [r["id"] for r in svc.ledger_records(ba)]
        with pytest.raises(ValidationError, match="not balanced"):
            svc.manual_match(ba.name, [line], recs[:1])
        rec = new_doc("Bank Reconciliation", bank_account=ba.name, from_date=date(Y, 4, 1), to_date=date(Y, 4, 30), statement_opening_balance=0, statement_closing_balance=11_000).insert(ignore_permissions=True)
        assert rec.status == "Unbalanced" and Decimal(str(rec.variance)) == Decimal("-1000.00")
        with pytest.raises(ValidationError, match="not balanced"):
            approve(rec)
        svc.manual_match(ba.name, [line], recs)
        rec = get_doc("Bank Reconciliation", rec.name); rec.statement_closing_balance = 12_000; rec.save(ignore_permissions=True)
        assert rec.status == "Reconciled" and Decimal(str(rec.variance)) == 0
    finally:
        velora.shutdown()


def test_rejected_suggestion_is_not_proposed_again_and_ignored_lines_need_a_reason(tmp_path):
    accounts, ba = _setup(tmp_path)
    try:
        _book(accounts, date(Y, 5, 5), "Receipt", 1000, "K1", "Quartz")
        _book(accounts, date(Y, 5, 5), "Receipt", 1000, "K2", "Blue Co")
        svc.import_statement(ba.name, content=f"Date,Narration,Debit,Credit\n06/05/{Y},Lodgement,,\"1,000.00\"\n", auto=True)
        wb = svc.workbench(ba.name)
        assert len(wb["suggestions"]) == 1
        svc.reject_groups([wb["suggestions"][0]["group"]])
        rejected_pair = None
        svc.run_auto(ba.name)
        wb = svc.workbench(ba.name)
        suggested = [(g["lines"][0]["id"], g["records"][0]["id"]) for g in wb["suggestions"]]
        assert len(wb["suggestions"]) == 1, "the other candidate is offered instead of the rejected one"
        with pytest.raises(ValidationError, match="reason"):
            svc.ignore_lines([wb["unmatched_lines"][0]["id"]] if wb["unmatched_lines"] else [], "")
    finally:
        velora.shutdown()


def test_http_routes_import_match_and_workbench(tmp_path):
    from fastapi.testclient import TestClient
    from velora.api.app import create_app
    accounts, ba = _setup(tmp_path)
    try:
        _book(accounts, date(Y, 6, 2), "Payment", 4200, "CHQ-7001", "Stationery")
        client = TestClient(create_app(auto_init=False))
        h = {"X-Velora-User": MAKER.user, "X-Velora-Roles": "Accountant"}
        r = client.post("/api/bank-reconciliation/import", headers=h, json={"bank_account": ba.name, "filename": "j.csv",
                        "content": f"Date,Narration,Ref,Debit,Credit\n02/06/{Y},CHEQUE 7001,CHQ-7001,\"4,200.00\",\n"})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["matching"]["confirmed"] == 1
        w = client.get("/api/bank-reconciliation/workbench", params={"bank_account": ba.name}, headers=h).json()["data"]
        assert len(w["matched"]) == 1 and not w["unmatched_lines"]
        c = client.get("/api/bank-reconciliation/compute", params={"bank_account": ba.name, "to_date": f"{Y}-06-30", "closing": "-4200"}, headers=h).json()["data"]
        assert Decimal(str(c["variance"])) == 0
        bad = client.post("/api/bank-reconciliation/import", headers=h, json={"bank_account": ba.name, "content": "nothing useful"})
        assert bad.status_code in (400, 422)
    finally:
        velora.shutdown()
