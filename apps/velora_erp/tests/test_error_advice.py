"""VeloraERP refusals come with what to do next, through the REST API."""
from datetime import date

import velora
from velora import new_doc
from velora.permissions import session_as

from test_cash_transactions import MAKER, setup_cash


def test_a_posting_outside_any_financial_year_is_advised_with_a_link(tmp_path):
    from fastapi.testclient import TestClient
    from velora.api.app import create_app
    a, c, s = setup_cash(tmp_path)
    try:
        client = TestClient(create_app(auto_init=False))
        h = {"X-Velora-User": "Administrator", "X-Velora-Roles": "System Manager,Finance Manager,Accountant"}
        def submit_on(day):
            body = {"invoice_date": day, "posting_date": day, "due_date": day, "party": c.name, "currency": "NGN", "exchange_rate": 1, "narration": "x",
                    "approval_status": "Approved", "lines": [{"account": a["4000"].name, "description": "s", "amount": 10}]}
            made = client.post("/api/resource/Sales Invoice", headers=h, json=body)
            assert made.status_code in (200, 201), made.text
            res = client.post(f"/api/resource/Sales Invoice/{made.json()['data']['name']}/submit", headers=h, json={})
            assert res.status_code >= 400
            return res.json()
        from datetime import timedelta
        j = submit_on(str(date(date.today().year, 1, 1) - timedelta(days=10)))      # inside the backdating window, before the only year
        assert "Financial Year" in j["message"]
        assert "Financial Year" in j["message"]
        assert j["advice"]["hint"].startswith("Create the Financial Year")
        assert j["advice"]["actions"][0]["href"] == "#/app/Financial%20Year/new"
        j = submit_on("2001-01-05")                                                   # far back: the backdating rule answers
        assert "backdating" in j["message"] and j["advice"]["actions"][0]["href"] == "#/app/Finance%20Settings"
    finally:
        velora.shutdown()


def test_every_erp_rule_is_well_formed():
    import re
    from velora_erp.advice_rules import RULES
    for r in RULES:
        re.compile(r["pattern"])
        assert r["hint"].strip().endswith((".", ")")), r
        for x in r.get("actions", []):
            assert x["href"].startswith("#/") and x["label"]


def test_exchange_rate_missing_is_advised_and_an_old_rate_is_a_note_not_a_block(tmp_path):
    from datetime import timedelta
    from fastapi.testclient import TestClient
    from velora.api.app import create_app
    a, c, s = setup_cash(tmp_path)
    try:
        client = TestClient(create_app(auto_init=False))
        h = {"X-Velora-User": "Administrator", "X-Velora-Roles": "System Manager,Finance Manager,Accountant"}
        today = date.today().isoformat()
        body = {"invoice_date": today, "posting_date": today, "due_date": today, "party": c.name, "currency": "USD", "exchange_rate": 0, "narration": "x",
                "lines": [{"account": a["4000"].name, "description": "s", "amount": 10}]}
        res = client.post("/api/resource/Sales Invoice", headers=h, json=body)
        assert res.status_code in (417, 422), res.text
        assert res.json()["advice"]["field"] == "exchange_rate", res.text
        assert res.json()["advice"]["actions"][0]["href"] == "#/app/Currency%20Exchange%20Rate/new"
        new_doc("Currency Exchange Rate", from_currency="USD", to_currency="NGN", rate=1500, effective_date=date.today() - timedelta(days=20)).insert(ignore_permissions=True)
        ok = client.post("/api/resource/Sales Invoice", headers=h, json=body)
        assert ok.status_code in (200, 201), ok.text
        assert float(ok.json()["data"]["exchange_rate"]) == 1500
        notes = ok.json()["warnings"]
        assert len(notes) == 1 and "20 days before this document" in notes[0]["message"]
    finally:
        velora.shutdown()
