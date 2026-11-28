"""Auto-allocation of a receipt/payment across a party's open invoices."""
from decimal import Decimal
import pytest
from velora_erp.finance import invoice_settlement as s

D = Decimal


def _fake(monkeypatch, outs):
    rows = [{"invoice": n, "invoice_date": f"2026-01-{i+1:02d}", "due_date": f"2026-02-{i+1:02d}", "currency": "NGN", "invoice_total": D(o),
             "amount_settled": D(0), "outstanding": D(o), "payment_status": "Unpaid"} for i, (n, o) in enumerate(outs)]
    monkeypatch.setattr(s, "outstanding_invoices", lambda *a, **k: [dict(r) for r in rows])


def test_fifo_pays_oldest_first_and_leaves_an_advance(monkeypatch):
    _fake(monkeypatch, [("INV-1", 100), ("INV-2", 200), ("INV-3", 300)])
    r = s.suggest_allocations("Customer", "C", 350)
    assert [(a["invoice"], a["allocate"]) for a in r["allocations"]] == [("INV-1", D(100)), ("INV-2", D(200)), ("INV-3", D(50))]
    assert r["unapplied"] == 0
    assert s.suggest_allocations("Customer", "C", 700)["unapplied"] == D(100)


def test_best_match_clears_whole_invoices_when_a_combination_equals_the_amount(monkeypatch):
    _fake(monkeypatch, [("INV-1", 100), ("INV-2", 250), ("INV-3", 300), ("INV-4", 50)])
    r = s.suggest_allocations("Customer", "C", 350, method="Best Match")
    assert {a["invoice"] for a in r["allocations"]} == {"INV-1", "INV-2"} or {a["invoice"] for a in r["allocations"]} == {"INV-3", "INV-4"}
    assert all(a["allocate"] == a["outstanding"] for a in r["allocations"]) and r["allocated"] == D(350)
    fallback = s.suggest_allocations("Customer", "C", 333, method="Best Match")
    assert fallback["allocated"] == D(333) and "oldest" in fallback["explanation"].lower()


def test_reference_match_takes_invoices_named_in_the_reference_first(monkeypatch):
    _fake(monkeypatch, [("INV-1", 100), ("INV-2", 200), ("INV-3", 300)])
    r = s.suggest_allocations("Customer", "C", 300, method="Reference Match", reference_text="Payment for inv-3 thanks")
    assert [a["invoice"] for a in r["allocations"]] == ["INV-3"]


def test_largest_and_smallest_first_and_bad_method(monkeypatch):
    _fake(monkeypatch, [("INV-1", 100), ("INV-2", 200), ("INV-3", 300)])
    assert s.suggest_allocations("Customer", "C", 100, method="Largest First")["allocations"][0]["invoice"] == "INV-3"
    assert s.suggest_allocations("Customer", "C", 100, method="Smallest First")["allocations"][0]["invoice"] == "INV-1"
    with pytest.raises(Exception):
        s.suggest_allocations("Customer", "C", 100, method="Magic")
