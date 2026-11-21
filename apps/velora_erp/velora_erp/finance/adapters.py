"""Stable source-adapter contract for VeloraERP financial posting.

Source modules translate validated business documents into PostingInstruction
objects and submit them through :func:`post_source_document`. Adapters must
never write Account Ledger Record rows or Financial Posting Batch rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from velora import throw


@dataclass(frozen=True)
class PostingLine:
    """One classified debit or credit instruction; never a ledger record."""

    account: str
    debit: Decimal | str | int = Decimal("0")
    credit: Decimal | str | int = Decimal("0")
    party_type: str | None = None
    party: str | None = None
    cost_centre: str | None = None
    dimensions: dict[str, str] = field(default_factory=dict)
    line_description: str = ""
    transaction_date: date | None = None
    due_date: date | None = None
    value_date: date | None = None
    source_line_reference: str | None = None
    external_reference: str | None = None
    settlement_reference: str | None = None
    tax_code: str | None = None
    tax_rate: Decimal | str | int = Decimal("0")
    taxable_amount: Decimal | str | int = Decimal("0")
    tax_amount: Decimal | str | int = Decimal("0")
    base_taxable_amount: Decimal | str | int = Decimal("0")
    base_tax_amount: Decimal | str | int = Decimal("0")
    tax_jurisdiction: str | None = None
    item: str | None = None
    warehouse: str | None = None
    asset: str | None = None
    project: str | None = None
    business_unit: str | None = None
    branch: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "debit": self.debit,
            "credit": self.credit,
            "party_type": self.party_type,
            "party": self.party,
            "cost_centre": self.cost_centre,
            "dimensions": dict(self.dimensions),
            "line_description": self.line_description,
            "transaction_date": self.transaction_date, "due_date": self.due_date,
            "value_date": self.value_date, "source_line_reference": self.source_line_reference,
            "external_reference": self.external_reference, "settlement_reference": self.settlement_reference,
            "tax_code": self.tax_code, "tax_rate": self.tax_rate,
            "taxable_amount": self.taxable_amount, "tax_amount": self.tax_amount,
            "base_taxable_amount": self.base_taxable_amount, "base_tax_amount": self.base_tax_amount,
            "tax_jurisdiction": self.tax_jurisdiction, "item": self.item,
            "warehouse": self.warehouse, "asset": self.asset, "project": self.project,
            "business_unit": self.business_unit, "branch": self.branch,
        }


@dataclass(frozen=True)
class PostingInstruction:
    """Complete posting request produced by a source adapter."""

    posting_date: date
    currency: str
    idempotency_key: str
    lines: tuple[PostingLine, ...]
    exchange_rate: Decimal | str | int = Decimal("1")
    posting_event: str = "Original"
    remarks: str = ""


@runtime_checkable
class SourcePostingAdapter(Protocol):
    """Adapter contract implemented by each financial source module."""

    def build_posting(self, source: Any) -> PostingInstruction:
        """Return validated accounting instructions for a submitted source."""
        ...


def post_source_document(source: Any, adapter: SourcePostingAdapter):
    """Post a submitted source document using the central posting engine.

    The source document must already be in its submit transaction. The caller
    must invoke this from the source document's submit lifecycle hook so a
    posting exception rolls back both source submission and ledger persistence.
    """
    doctype = getattr(source, "doctype", None)
    name = getattr(source, "name", None)
    if not doctype or not name:
        throw("A source adapter requires a persisted source document with DocType and name.")
    if getattr(source, "docstatus", None) != 1:
        throw(f"Source document {doctype} {name} must be submitted before financial posting.")
    if not isinstance(adapter, SourcePostingAdapter):
        throw("The source adapter must implement build_posting(source).")

    instruction = adapter.build_posting(source)
    if not isinstance(instruction, PostingInstruction):
        throw("Source adapter build_posting() must return a PostingInstruction.")
    key = (instruction.idempotency_key or "").strip()
    if not key:
        throw("Source adapters must supply a stable, non-empty idempotency key.")
    if len(key) > 255:
        throw("Source adapter idempotency keys cannot exceed 255 characters.")
    if not instruction.lines or any(not isinstance(line, PostingLine) for line in instruction.lines):
        throw("PostingInstruction.lines must contain one or more PostingLine objects.")
    if not isinstance(instruction.posting_date, date):
        throw("PostingInstruction.posting_date must be a date.")
    if not instruction.currency or len(instruction.currency.strip()) != 3:
        throw("PostingInstruction.currency must be a three-letter currency code.")

    # Local import avoids coupling the contract definitions to engine import time.
    from .engine import post_financial_transaction

    return post_financial_transaction(
        source_doctype=doctype,
        source_name=name,
        posting_date=instruction.posting_date,
        currency=instruction.currency.strip().upper(),
        exchange_rate=instruction.exchange_rate,
        posting_event=instruction.posting_event,
        remarks=instruction.remarks,
        idempotency_key=key,
        lines=[line.as_payload() for line in instruction.lines],
    )
