"""Read-only API helpers for native Velora Desk Create From menus."""
from velora import get_doc, throw
from .registry import get_document_flows


def get_create_from_actions(source_doctype: str, source_name: str) -> list[dict]:
    """Return the Create From actions that fit this record right now (submitted, draft or open documents, depending on the flow)."""
    source = get_doc(source_doctype, source_name)
    return get_document_flows(source_doctype, doc=source)


def get_document_flow_catalogue(source_doctype: str | None = None) -> list[dict]:
    """Return configured and planned transitions for administration/design UI."""
    from .registry import DOCUMENT_FLOWS
    rows = get_document_flows(source_doctype, include_planned=True) if source_doctype else []
    if source_doctype:
        return rows
    for flow in DOCUMENT_FLOWS:
        rows.append({
            "source_doctype": flow.source_doctype,
            "target_doctype": flow.target_doctype,
            "label": flow.label,
            "status": flow.status,
            "available": flow.status == "active" and bool(flow.handler),
            "cardinality": flow.cardinality,
            "description": flow.description,
        })
    return rows


# Provider entry point consumed by the framework generic document-flow REST API.
from .conversion import create_document_from


def _settlement_party(body):
    party_type = str(body.get("party_type") or "").strip()
    party = str(body.get("party") or "").strip()
    if party_type not in {"Customer", "Supplier"} or not party:
        throw("Select a Customer or Supplier first.")
    return party_type, party


def settlement_outstanding(body: dict) -> dict:
    """Open invoices of a party for the Apply to Invoices table (permission checked through the party read)."""
    from velora_erp.finance.invoice_settlement import outstanding_invoices, STRATEGIES
    party_type, party = _settlement_party(body)
    get_doc(party_type, party)
    rows = outstanding_invoices(party_type, party, as_of=body.get("as_of") or None, currency=body.get("currency") or None)
    return {"invoices": rows, "methods": list(STRATEGIES)}


def settlement_allocate(body: dict) -> dict:
    """Auto-allocate an amount over a party's open invoices and return ready-to-use document lines."""
    from velora_erp.finance.invoice_settlement import suggest_allocations, build_lines_from_allocations
    party_type, party = _settlement_party(body)
    doc = get_doc(party_type, party)
    control = getattr(doc, "control_account", None)
    if not control:
        throw(f"Configure the {party_type}'s control account first.")
    chosen = body.get("allocations")
    if chosen:
        from decimal import Decimal
        from velora_erp.finance.invoice_settlement import outstanding_invoices
        open_by_name = {r["invoice"]: r for r in outstanding_invoices(party_type, party, as_of=body.get("as_of") or None, currency=body.get("currency") or None)}
        picked, used = [], Decimal("0")
        for item in chosen:
            inv = open_by_name.get(str(item.get("invoice")))
            take = Decimal(str(item.get("allocate") or 0))
            if not inv or take <= 0 or take > inv["outstanding"]:
                throw(f"Invoice {item.get('invoice')} is not open for that amount.")
            picked.append({**inv, "allocate": take}); used += take
        amount = Decimal(str(body.get("amount") or used))
        if used > amount:
            throw("The allocated amount exceeds the amount entered.")
        result = {"allocations": picked, "allocated": used, "unapplied": amount - used, "method": "Manual", "explanation": "Allocated by hand."}
    else:
        result = suggest_allocations(party_type, party, body.get("amount"), as_of=body.get("as_of") or None, currency=body.get("currency") or None,
                                     method=body.get("method") or "FIFO", reference_text=body.get("reference_text"))
    result["lines"] = build_lines_from_allocations(party_type, party, control, result["allocations"], unapplied=result["unapplied"])
    return result


# Get Items From (a draft Purchase Receipt / Purchase Invoice / Delivery Note / Sales Invoice takes lines from open orders, receipts or deliveries)
def pull_sources(target_doctype: str) -> list[str]:
    from .pull import sources_for
    return sources_for(target_doctype)


def pull_candidates(body: dict) -> list[dict]:
    from .pull import candidates
    return candidates(str(body.get("target_doctype") or ""), str(body.get("source_doctype") or ""), body.get("party") or None,
                      str(body.get("txt") or ""), body.get("exclude") or None)


def pull_items(body: dict) -> dict:
    from .pull import pull
    return pull(str(body.get("target_doctype") or ""), str(body.get("source_doctype") or ""), list(body.get("names") or []),
                body.get("party") or None, body.get("exclude") or None)
