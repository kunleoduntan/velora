"""Central, append-only financial posting engine for VeloraERP.

Business documents submit classified posting instructions here. This module is the
only supported writer of Account Ledger Record rows. All amounts use Decimal and
all batch/ledger writes share the caller's database transaction.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from velora.exceptions import DuplicateEntryError

from velora import db, get_doc, new_doc, throw
from velora.meta.registry import registry
from velora.db.tables import get_table
from .validation import row

ZERO = Decimal("0")


def _decimal(value, label: str) -> Decimal:
    try:
        amount = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, TypeError, ValueError):
        throw(f"{label} must be a valid decimal amount")
    if not amount.is_finite():
        throw(f"{label} must be a finite decimal amount")
    return amount


def _money(value: Decimal, places: int) -> Decimal:
    quantum = Decimal("1").scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _decimal_text(value) -> str:
    amount = _decimal(value, "Financial amount").normalize()
    return format(amount, "f")


def _canonical_hash(batch) -> str:
    lines = []
    for line in batch.lines or []:
        lines.append({
            "account": line.account,
            "debit": _decimal_text(line.debit),
            "credit": _decimal_text(line.credit),
            "base_debit": _decimal_text(line.base_debit),
            "base_credit": _decimal_text(line.base_credit),
            "party_type": line.party_type or None,
            "party": line.party or None,
            "cost_centre": line.cost_centre or None,
            "dimensions": line.dimensions or {},
            "description": line.line_description or "",
            "transaction_date": str(line.transaction_date) if line.transaction_date else None,
            "due_date": str(line.due_date) if line.due_date else None,
            "value_date": str(line.value_date) if line.value_date else None,
            "source_line_reference": line.source_line_reference or None,
            "external_reference": line.external_reference or None,
            "settlement_reference": line.settlement_reference or None,
            "tax_code": line.tax_code or None,
            "tax_rate": _decimal_text(line.tax_rate or 0),
            "taxable_amount": _decimal_text(line.taxable_amount or 0),
            "tax_amount": _decimal_text(line.tax_amount or 0),
            "base_taxable_amount": _decimal_text(line.base_taxable_amount or 0),
            "base_tax_amount": _decimal_text(line.base_tax_amount or 0),
            "tax_jurisdiction": line.tax_jurisdiction or None,
            "item": line.item or None, "warehouse": line.warehouse or None,
            "asset": line.asset or None, "project": line.project or None,
            "business_unit": line.business_unit or None, "branch": line.branch or None,
        })
    payload = {
        "source_doctype": batch.source_doctype,
        "source_name": batch.source_name,
        "posting_event": batch.posting_event,
        "posting_date": batch.posting_date.isoformat() if hasattr(batch.posting_date, "isoformat") else str(batch.posting_date),
        "financial_year": batch.financial_year,
        "financial_period": batch.financial_period,
        "currency": batch.currency,
        "exchange_rate": _decimal_text(batch.exchange_rate),
        "base_currency": batch.base_currency,
        "lines": lines,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_key(source_doctype: str, source_name: str, posting_event: str) -> str:
    raw = f"{source_doctype.strip()}\x1f{source_name.strip()}\x1f{posting_event.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _settings() -> dict:
    table = get_table("Finance Settings")
    with db.transaction() as conn:
        result = conn.execute(select(table).limit(1)).mappings().first()
    if not result:
        throw("Finance Settings have not been configured. Complete Finance Settings before posting.")
    from velora_erp.configuration import apply_governed_settings
    return apply_governed_settings("Finance Settings", dict(result))


def _resolve_period(posting_date: date) -> tuple[str, str]:
    years = get_table("Financial Year")
    periods = get_table("Financial Period")
    with db.transaction() as conn:
        year = conn.execute(
            select(years.c.name, years.c.status)
            .where(years.c.start_date <= posting_date, years.c.end_date >= posting_date)
            .limit(2)
        ).mappings().all()
        period = conn.execute(
            select(periods.c.name, periods.c.financial_year, periods.c.status)
            .where(periods.c.start_date <= posting_date, periods.c.end_date >= posting_date)
            .limit(2)
        ).mappings().all()
    if len(year) != 1:
        throw("The posting date must belong to exactly one configured Financial Year.")
    if year[0]["status"] != "Open":
        throw(f"Financial Year {year[0]['name']} is not open for posting.")
    if len(period) != 1:
        throw("The posting date must belong to exactly one configured Financial Period.")
    if period[0]["financial_year"] != year[0]["name"]:
        throw("The Financial Period and Financial Year do not match.")
    if period[0]["status"] != "Open":
        throw(f"Financial Period {period[0]['name']} is not open for posting.")
    return year[0]["name"], period[0]["name"]


def _validate_dimensions(values: dict | None) -> dict:
    if values is None:
        values = {}
    if not isinstance(values, dict):
        throw("Accounting Dimensions must be supplied as an object of dimension code and value pairs.")
    dimension_table = get_table("Accounting Dimension")
    with db.transaction() as conn:
        dimensions = [dict(r) for r in conn.execute(select(dimension_table).where(dimension_table.c.disabled == 0)).mappings()]
    by_code = {d["dimension_code"]: d for d in dimensions}
    by_name = {d["name"]: d for d in dimensions}
    normalised = {}
    for key, value in values.items():
        dimension = by_code.get(str(key)) or by_name.get(str(key))
        if not dimension:
            throw(f"Accounting Dimension {key!r} is not configured or is disabled.")
        if value in (None, ""):
            throw(f"A value is required for Accounting Dimension {dimension['dimension_name']}.")
        value = str(value).strip()
        if not value:
            throw(f"A value is required for Accounting Dimension {dimension['dimension_name']}.")
        if dimension["value_source"] == "Dimension Values":
            value_table = get_table("Dimension Value")
            with db.transaction() as conn:
                candidate = conn.execute(
                    select(value_table.c.name, value_table.c.is_group, value_table.c.disabled)
                    .where(value_table.c.dimension == dimension["name"])
                    .where((value_table.c.name == value) | (value_table.c.value_code == value))
                    .limit(1)
                ).mappings().first()
            if not candidate or candidate["disabled"] or candidate["is_group"]:
                throw(f"{value!r} is not an active posting value for dimension {dimension['dimension_name']}.")
            value = candidate["name"]
        normalised[dimension["dimension_code"]] = value
    for dimension in dimensions:
        if dimension["mandatory_on_posting"] and dimension["dimension_code"] not in normalised:
            throw(f"Accounting Dimension {dimension['dimension_name']} is mandatory on financial posting.")
    return normalised


def _validate_account(account_name: str, currency: str, line_no: int, source_doctype: str, posting_event: str = "Original") -> dict:
    account = row("Account", account_name, "name", "account_group", "account_type", "account_currency", "requires_party", "allow_manual_posting", "disabled", "frozen", "requires_cost_centre", "is_group")
    if not account:
        throw(f"Line {line_no}: Account {account_name!r} does not exist.")
    if account["disabled"]:
        throw(f"Line {line_no}: Account {account_name} is disabled.")
    if account.get("frozen"):
        throw(f"Line {line_no}: Account {account_name} is frozen; no new postings are allowed.")
    if account.get("is_group"):
        throw(f"Line {line_no}: Account {account_name} is a group account. Post to one of the accounts under it.")
    group = row("Account Group", account["account_group"], "name", "disabled")
    if not group or group["disabled"]:
        throw(f"Line {line_no}: Account {account_name} belongs to a missing or disabled Account Group.")
    if account["account_currency"] and account["account_currency"] != currency:
        throw(f"Line {line_no}: Account {account_name} is restricted to {account['account_currency']}.")
    if source_doctype == "Financial Voucher" and not account["allow_manual_posting"]:
        throw(f"Line {line_no}: Manual posting is disabled for Account {account_name}.")
    return account


def _validate_party(party_type: str | None, party_name: str | None, account_name: str, line_no: int):
    if not party_type and not party_name:
        return
    if party_type not in ("Customer", "Supplier", "Employee"):
        throw(f"Line {line_no}: Party Type must be Customer, Supplier or Employee.")
    party = row(party_type, party_name, "name", "disabled")
    if not party:
        throw(f"Line {line_no}: {party_type} {party_name!r} does not exist.")
    if party["disabled"]:
        throw(f"Line {line_no}: {party_type} {party_name} is disabled.")
    account = row("Account", account_name, "name", "root_type", "requires_party")
    expected_roots = {"Customer": ("Asset", "Liability"), "Supplier": ("Asset", "Liability"), "Employee": ("Asset", "Liability")}
    allowed_roots = expected_roots[party_type]
    if not account or account["root_type"] not in allowed_roots or not account["requires_party"]:
        allowed = " or ".join(allowed_roots)
        throw(f"Line {line_no}: {party_type} postings require a party-tracked {allowed} account.")


def _validate_cost_centre(cost_centre: str | None, line_no: int):
    if not cost_centre:
        return
    centre = row("Cost Centre", cost_centre, "name", "is_group", "disabled")
    if not centre or centre["disabled"] or centre["is_group"]:
        throw(f"Line {line_no}: Cost Centre {cost_centre!r} must be an active posting-level Cost Centre.")


def prepare_batch(batch):
    """Derive and validate every posting control before a batch can be submitted."""
    if not batch.source_doctype or not batch.source_name:
        throw("Source Document Type and Source Document are required.")
    batch.source_doctype = batch.source_doctype.strip()
    batch.source_name = batch.source_name.strip()
    batch.posting_event = batch.posting_event or "Original"
    if batch.posting_event not in ("Original", "Adjustment", "Opening Balance"):
        throw("Select a valid Posting Event.")
    batch.source_key = _source_key(batch.source_doctype, batch.source_name, batch.posting_event)
    if not batch.posting_date:
        throw("Posting Date is required.")
    settings = _settings()
    if not settings.get("allow_backdated_posting") and batch.posting_date < date.today():
        throw("Backdated posting is disabled in Finance Settings.")
    backdated_days = settings.get("backdated_posting_days")
    if settings.get("allow_backdated_posting") and backdated_days is not None:
        earliest = date.today() - timedelta(days=int(backdated_days))
        if batch.posting_date < earliest:
            throw(f"Posting Date is outside the permitted backdating window of {backdated_days} days.")
    # If the source DocType is installed, it must exist and already be submitted.
    # During a source document's on_submit hook the framework has persisted docstatus=1
    # inside the same transaction, so the source and ledger remain atomic.
    if batch.source_doctype in registry._doctypes:
        source_table = get_table(batch.source_doctype)
        with db.transaction() as conn:
            source = conn.execute(
                select(source_table.c.name, source_table.c.docstatus)
                .where(source_table.c.name == batch.source_name).limit(1)
            ).mappings().first()
        if not source or source["docstatus"] != 1:
            throw(f"Source document {batch.source_doctype} {batch.source_name} must exist and be submitted before financial posting.")
    batch.base_currency = (settings.get("base_currency") or "").upper()
    batch.currency = (batch.currency or batch.base_currency).upper()
    if len(batch.currency) != 3 or not batch.currency.isalpha():
        throw("Transaction Currency must be a three-letter ISO currency code.")
    if len(batch.base_currency) != 3:
        throw("Configure a valid three-letter Base Currency in Finance Settings.")
    rate = _decimal(batch.exchange_rate or 1, "Exchange rate")
    if rate <= 0:
        throw("Exchange Rate must be greater than zero.")
    if batch.currency == batch.base_currency and rate != Decimal("1"):
        throw("Exchange Rate must be 1 when transaction currency equals base currency.")
    batch.exchange_rate = rate
    batch.financial_year, batch.financial_period = _resolve_period(batch.posting_date)
    places = int(settings.get("decimal_places") or 2)
    if not 0 <= places <= 6:
        throw("Finance Settings currency decimal places must be between 0 and 6.")
    if not batch.lines or len(batch.lines) < 2:
        throw("A financial posting batch requires at least two lines.")
    total_debit = total_credit = total_base_debit = total_base_credit = ZERO
    for index, line in enumerate(batch.lines, 1):
        account = _validate_account(line.account, batch.currency, index, batch.source_doctype, batch.posting_event)
        debit = _decimal(line.debit, f"Line {index} debit")
        credit = _decimal(line.credit, f"Line {index} credit")
        if debit < ZERO or credit < ZERO:
            throw(f"Line {index}: debit and credit amounts cannot be negative.")
        if debit and credit:
            throw(f"Line {index}: enter either a debit or a credit, not both.")
        if not debit and not credit:
            throw(f"Line {index}: a non-zero debit or credit amount is required.")
        if account["requires_party"] and (not line.party_type or not line.party):
            throw(f"Line {index}: Account {line.account} requires both Party Type and Party.")
        if bool(line.party_type) != bool(line.party):
            throw(f"Line {index}: Party Type and Party must be supplied together.")
        _validate_party(line.party_type, line.party, line.account, index)
        _validate_cost_centre(line.cost_centre, index)
        if account.get("requires_cost_centre") and not line.cost_centre and batch.posting_event != "Opening Balance":
            throw(f"Line {index}: Account {line.account} requires a Cost Centre.")
        line.dimensions = _validate_dimensions(line.dimensions)
        calculated_debit = _money(debit * rate, places)
        calculated_credit = _money(credit * rate, places)
        supplied_base_debit = _decimal(line.base_debit, f"Line {index} base debit")
        supplied_base_credit = _decimal(line.base_credit, f"Line {index} base credit")
        base_debit = supplied_base_debit if supplied_base_debit else calculated_debit
        base_credit = supplied_base_credit if supplied_base_credit else calculated_credit
        if base_debit < ZERO or base_credit < ZERO or (base_debit and base_credit):
            throw(f"Line {index}: base currency amounts must be non-negative and debit or credit, not both.")
        if base_debit != calculated_debit or base_credit != calculated_credit:
            throw(f"Line {index}: base currency amount does not agree with transaction amount and exchange rate. Add an explicit exchange rounding line if required.")
        tax_rate = _decimal(line.tax_rate or 0, f"Line {index} tax rate")
        taxable_amount = _decimal(line.taxable_amount or 0, f"Line {index} taxable amount")
        tax_amount = _decimal(line.tax_amount or 0, f"Line {index} tax amount")
        if tax_rate < ZERO or taxable_amount < ZERO or tax_amount < ZERO:
            throw(f"Line {index}: tax rate, taxable amount and tax amount cannot be negative.")
        calculated_base_taxable = _money(taxable_amount * rate, places)
        calculated_base_tax = _money(tax_amount * rate, places)
        supplied_base_taxable = _decimal(line.base_taxable_amount or 0, f"Line {index} base taxable amount")
        supplied_base_tax = _decimal(line.base_tax_amount or 0, f"Line {index} base tax amount")
        if supplied_base_taxable and supplied_base_taxable != calculated_base_taxable:
            throw(f"Line {index}: base taxable amount does not agree with transaction currency and exchange rate.")
        if supplied_base_tax and supplied_base_tax != calculated_base_tax:
            throw(f"Line {index}: base tax amount does not agree with transaction currency and exchange rate.")
        line.tax_rate, line.taxable_amount, line.tax_amount = tax_rate, taxable_amount, tax_amount
        line.base_taxable_amount, line.base_tax_amount = calculated_base_taxable, calculated_base_tax
        line.debit, line.credit = debit, credit
        line.base_debit, line.base_credit = base_debit, base_credit
        total_debit += debit
        total_credit += credit
        total_base_debit += base_debit
        total_base_credit += base_credit
    if total_debit != total_credit:
        throw(f"Transaction currency debits ({total_debit}) and credits ({total_credit}) must balance.")
    if total_base_debit != total_base_credit:
        throw(f"Base currency debits ({total_base_debit}) and credits ({total_base_credit}) must balance. This release does not yet support base-only currency rounding adjustments; posting is blocked rather than silently unbalanced.")
    if total_debit == ZERO:
        throw("A zero-value financial posting batch is not permitted.")
    batch.total_debit = total_debit
    batch.total_credit = total_credit
    batch.total_base_debit = total_base_debit
    batch.total_base_credit = total_base_credit
    # A saved draft is not represented as posted. The submit hook changes this
    # status in the same transaction that writes the immutable ledger records.
    batch.posting_status = "Draft"
    batch.posting_hash = _canonical_hash(batch)
    return batch


def _write_ledger(batch):
    for line in batch.lines:
        account_snapshot = row("Account", line.account, "name", "account_code", "account_name", "account_group", "root_type", "normal_balance")
        entry_key = hashlib.sha256(f"{batch.name}:{line.name}".encode("utf-8")).hexdigest()
        entry = new_doc(
            "Account Ledger Record",
            entry_key=entry_key,
            posting_batch=batch.name,
            posting_line=line.name,
            source_doctype=batch.source_doctype,
            source_name=batch.source_name,
            posting_event=batch.posting_event,
            posting_date=batch.posting_date,
            financial_year=batch.financial_year,
            financial_period=batch.financial_period,
            account=line.account,
            currency=batch.currency,
            exchange_rate=batch.exchange_rate,
            debit=line.debit,
            credit=line.credit,
            base_currency=batch.base_currency,
            base_debit=line.base_debit,
            base_credit=line.base_credit,
            party_type=line.party_type,
            party=line.party,
            cost_centre=line.cost_centre,
            dimensions=line.dimensions,
            line_description=line.line_description,
            transaction_date=line.transaction_date, due_date=line.due_date, value_date=line.value_date,
            source_line_reference=line.source_line_reference, external_reference=line.external_reference,
            settlement_reference=line.settlement_reference, tax_code=line.tax_code, tax_rate=line.tax_rate,
            taxable_amount=line.taxable_amount, tax_amount=line.tax_amount, item=line.item,
            warehouse=line.warehouse, asset=line.asset, project=line.project,
            business_unit=line.business_unit, branch=line.branch,
            base_taxable_amount=line.base_taxable_amount, base_tax_amount=line.base_tax_amount,
            tax_jurisdiction=line.tax_jurisdiction,
            account_code_snapshot=account_snapshot.get("account_code") if account_snapshot else None,
            account_name_snapshot=account_snapshot.get("account_name") if account_snapshot else None,
            account_group_snapshot=account_snapshot.get("account_group") if account_snapshot else None,
            root_type_snapshot=account_snapshot.get("root_type") if account_snapshot else None,
            normal_balance_snapshot=account_snapshot.get("normal_balance") if account_snapshot else None,
        )
        entry.flags.posting_engine_authorized = True
        entry.insert(ignore_permissions=True)


def post_financial_transaction(*, source_doctype: str, source_name: str, posting_date: date,
                               currency: str, lines: list[dict], exchange_rate=1,
                               posting_event: str = "Original", remarks: str = "",
                               idempotency_key: str | None = None):
    """Post a balanced financial event exactly once and return its submitted batch.

    Idempotency is enforced by source document + posting event and, optionally,
    a caller-provided idempotency key. Repeating identical content returns the
    existing batch; attempting different content under the same key is rejected.
    """
    batch = new_doc(
        "Financial Posting Batch",
        source_doctype=source_doctype,
        source_name=source_name,
        posting_event=posting_event,
        posting_date=posting_date,
        currency=currency,
        exchange_rate=exchange_rate,
        idempotency_key=idempotency_key,
        remarks=remarks,
        lines=lines,
    )
    prepare_batch(batch)
    table = get_table("Financial Posting Batch")

    def existing_batch_for_key():
        with db.transaction() as conn:
            existing = conn.execute(
                select(table.c.name, table.c.posting_hash, table.c.docstatus)
                .where(table.c.source_key == batch.source_key).limit(1)
            ).mappings().first()
            if idempotency_key:
                by_key = conn.execute(
                    select(table.c.name, table.c.posting_hash, table.c.docstatus)
                    .where(table.c.idempotency_key == idempotency_key).limit(1)
                ).mappings().first()
                if by_key and (not existing or by_key["name"] != existing["name"]):
                    existing = by_key
        return existing

    existing = existing_batch_for_key()
    if not existing:
        # Budget control applies only to a genuinely new posting (never to an idempotent repeat).
        from velora_erp.finance.budget_control import check_posting
        check_posting(lines=lines, posting_date=posting_date, exchange_rate=exchange_rate,
                      posting_event=posting_event, source_doctype=source_doctype)
    if existing:
        if existing["posting_hash"] != batch.posting_hash:
            throw("This source event or idempotency key has already been used for different financial content.")
        existing_batch = get_doc("Financial Posting Batch", existing["name"], ignore_permissions=True)
        if existing["docstatus"] == 0:
            existing_batch.submit(ignore_permissions=True)
            existing_batch.reload()
        return existing_batch
    try:
        with db.transaction() as conn:
            # A SAVEPOINT, not just a transaction: when this runs inside the source document's own
            # submit transaction, losing the unique-key race must not abort that whole transaction
            # (on PostgreSQL every later statement would fail), so the lookup below can still run.
            with conn.begin_nested():
                batch.insert(ignore_permissions=True)
                batch.submit(ignore_permissions=True)
    except (IntegrityError, DuplicateEntryError):
        # A concurrent request may have won the unique source/idempotency key race. The framework
        # reports a unique violation as DuplicateEntryError (it never surfaces a raw IntegrityError
        # from Document.insert), so both are handled; the losing attempt is rolled back first.
        existing = existing_batch_for_key()
        if not existing:
            raise
        if existing["posting_hash"] != batch.posting_hash:
            throw("This source event or idempotency key has already been used for different financial content.")
        return get_doc("Financial Posting Batch", existing["name"], ignore_permissions=True)
    return get_doc("Financial Posting Batch", batch.name, ignore_permissions=True)


def get_account_balance(account: str, *, as_of: date | None = None,
                        party_type: str | None = None, party: str | None = None,
                        cost_centre: str | None = None) -> Decimal:
    """Return the account's net debit balance in company base currency."""
    table = get_table("Account Ledger Record")
    query = select(
        (func.coalesce(func.sum(table.c.base_debit), 0) - func.coalesce(func.sum(table.c.base_credit), 0))
    ).where(table.c.account == account)
    if as_of:
        query = query.where(table.c.posting_date <= as_of)
    if party_type:
        query = query.where(table.c.party_type == party_type)
    if party:
        query = query.where(table.c.party == party)
    if cost_centre:
        query = query.where(table.c.cost_centre == cost_centre)
    with db.transaction() as conn:
        value = conn.execute(query).scalar()
    return Decimal(str(value or 0))


def get_account_activity(account: str, *, from_date: date | None = None,
                         to_date: date | None = None, limit: int = 500) -> list[dict]:
    """Return immutable ledger rows for an account, in posting-date order."""
    table = get_table("Account Ledger Record")
    query = select(table).where(table.c.account == account).order_by(table.c.posting_date, table.c.creation, table.c.name).limit(max(1, min(int(limit), 5000)))
    if from_date:
        query = query.where(table.c.posting_date >= from_date)
    if to_date:
        query = query.where(table.c.posting_date <= to_date)
    with db.transaction() as conn:
        return [dict(r) for r in conn.execute(query).mappings()]
