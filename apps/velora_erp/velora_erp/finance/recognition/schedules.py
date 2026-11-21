"""Controlled prepayment amortisation and deferred-income recognition.

Schedules are approval-controlled source documents. A Purchase Invoice may create
pending Prepayment schedules automatically after the invoice is posted; those
schedules must still pass independent approval before they can recognise expense.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from velora import Document, get_doc, get_list, new_doc, throw
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import persist_posting_batch_link, validate_approval_transition, ensure_approved
from velora_erp.finance.validation import row

FREQUENCY_MONTHS = {"Monthly": 1, "Quarterly": 3, "Half-yearly": 6, "Yearly": 12}
CENT = Decimal("0.01")


def period_date(start: date, period_number: int, frequency: str = "Monthly") -> date:
    """Return the recognition date for a one-based period number."""
    if frequency not in FREQUENCY_MONTHS:
        throw("Frequency must be Monthly, Quarterly, Half-yearly or Yearly.")
    month_index = start.month - 1 + (period_number - 1) * FREQUENCY_MONTHS[frequency]
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def period_dates(start_date, end_date, frequency="Monthly") -> list[date]:
    start = start_date if isinstance(start_date, date) else date.fromisoformat(str(start_date))
    end = end_date if isinstance(end_date, date) else date.fromisoformat(str(end_date))
    if end < start:
        throw("End Date cannot be earlier than Start Date.")
    out = []
    for number in range(1, 601):
        due = period_date(start, number, frequency)
        if due > end:
            break
        out.append(due)
    if not out:
        throw("The selected date range does not contain a recognition period.")
    if len(out) >= 600 and period_date(start, 601, frequency) <= end:
        throw("A recognition schedule cannot exceed 600 periods.")
    return out


def period_amount(total, periods, period_number, places=2):
    quantum = Decimal("1").scaleb(-places)
    total = Decimal(str(total))
    regular = (total / Decimal(periods)).quantize(quantum, rounding=ROUND_HALF_UP)
    if period_number < periods:
        return regular
    return total - regular * (periods - 1)


def _set_period_count(doc):
    frequency = doc.frequency or "Monthly"
    if frequency not in FREQUENCY_MONTHS:
        throw("Frequency must be Monthly, Quarterly, Half-yearly or Yearly.")
    doc.frequency = frequency
    if doc.end_date:
        dates = period_dates(doc.start_date, doc.end_date, frequency)
        doc.period_count = len(dates)
    elif int(doc.period_count or 0) < 1:
        throw("Enter an End Date or a positive Period Count.")
    if int(doc.period_count or 0) > 600:
        throw("A recognition schedule cannot exceed 600 periods.")


class RecognitionSchedule(Document):
    def validate(self):
        if self.schedule_type not in ("Prepayment", "Deferred Income"):
            throw("Schedule Type must be Prepayment or Deferred Income.")
        if self.schedule_type == "Deferred Income":
            expected_source = "Receipt"
        elif self.source_doctype == "Purchase Invoice":
            expected_source = "Purchase Invoice"
        else:
            expected_source = "Payment"
        if self.source_doctype != expected_source:
            throw(f"{self.schedule_type} schedules must originate from a posted {expected_source}.")
        if not self.source_document:
            throw("Source document is required.")
        source = get_doc(expected_source, self.source_document, ignore_permissions=True)
        if source.docstatus != 1 or not source.posting_batch:
            throw(f"The source {expected_source} must be submitted and financially posted first.")
        if expected_source == "Payment" and source.purpose != "Prepayment":
            throw("The source Payment must have purpose Prepayment.")
        if expected_source == "Receipt" and source.purpose != "Deferred Income":
            throw("The source Receipt must have purpose Deferred Income.")
        if expected_source == "Purchase Invoice":
            if not source.is_amortised_cost:
                throw("The source Purchase Invoice must be marked Is Amortised Cost.")
            source_line = next((line for line in (source.lines or []) if str(getattr(line, "name", "")) == str(self.source_line)), None)
            if not source_line:
                throw("Source Invoice Line must belong to the selected Purchase Invoice.")
            if source_line.account != self.recognition_account:
                throw("Recognition Account must match the source Purchase Invoice line expense account.")
            if Decimal(str(self.total_amount or 0)) > Decimal(str(source_line.amount or 0)):
                throw("Schedule Total cannot exceed the source Purchase Invoice line amount.")
        else:
            if not self.source_doctype:
                throw("Source Receipt or Payment is required.")
            if Decimal(str(self.total_amount or 0)) > Decimal(str(source.total_accounting_amount or source.total_amount)):
                throw("Schedule Total cannot exceed the source transaction's gross accounting amount.")
        if not self.start_date:
            throw("Start Date is required.")
        _set_period_count(self)
        if Decimal(str(self.total_amount or 0)) <= 0:
            throw("Schedule Total must be greater than zero.")
        if not self.balance_account or not self.recognition_account:
            throw("Balance Account and Recognition Account are required.")
        balance = row("Account", self.balance_account, "name", "root_type", "disabled")
        recognition = row("Account", self.recognition_account, "name", "root_type", "disabled")
        if not balance or balance["disabled"] or not recognition or recognition["disabled"]:
            throw("Select active Balance and Recognition accounts.")
        roots = ("Asset", "Expense") if self.schedule_type == "Prepayment" else ("Liability", "Income")
        if (balance["root_type"], recognition["root_type"]) != roots:
            throw(f"{self.schedule_type} requires {roots[0]} Balance Account and {roots[1]} Recognition Account.")
        if self.cost_centre:
            cc = row("Cost Centre", self.cost_centre, "name", "disabled", "is_group")
            if not cc or cc["disabled"] or cc["is_group"]:
                throw("Select an active posting Cost Centre, not a group centre.")
        if self.business_unit:
            bu = row("Business Unit", self.business_unit, "name", "disabled")
            if not bu or bu["disabled"]:
                throw("Select an active Business Unit.")
        self.currency = source.currency
        self.exchange_rate = source.exchange_rate
        self.posting_batch_reference = source.posting_batch
        validate_approval_transition(self)

    def before_submit(self):
        ensure_approved(self, required=True)

    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Recognition Schedule cannot be deleted.")


class ScheduleRecognition(Document):
    def validate(self):
        schedule = get_doc("Recognition Schedule", self.schedule, ignore_permissions=True)
        if schedule.docstatus != 1:
            throw("Only an active submitted Recognition Schedule can be recognised.")
        period = int(self.period_number or 0)
        if period < 1 or period > int(schedule.period_count):
            throw("Period Number is outside the Recognition Schedule range.")
        expected_date = period_date(schedule.start_date, period, schedule.frequency or "Monthly")
        if self.recognition_date != expected_date:
            throw("Recognition Date does not match the schedule period date.")
        expected_amount = period_amount(schedule.total_amount, int(schedule.period_count), period)
        if Decimal(str(self.amount)) != expected_amount:
            throw(f"Recognition Amount must equal the scheduled amount {expected_amount}.")
        existing = get_list("Schedule Recognition", filters={"schedule": self.schedule, "period_number": period, "docstatus": 1}, fields=["name"], limit=1, ignore_permissions=True)
        if existing and existing[0]["name"] != self.name:
            throw("This schedule period has already been recognised.")
        self.currency = schedule.currency
        self.exchange_rate = schedule.exchange_rate
        self.balance_account = schedule.balance_account
        self.recognition_account = schedule.recognition_account
        self.schedule_type = schedule.schedule_type

    def on_submit(self):
        schedule = get_doc("Recognition Schedule", self.schedule, ignore_permissions=True)
        common = {"cost_centre": schedule.cost_centre or None, "business_unit": schedule.business_unit or None,
                  "line_description": f"Scheduled recognition {self.schedule}, period {self.period_number}"}
        if schedule.schedule_type == "Prepayment":
            lines = [
                {"account": self.recognition_account, "debit": self.amount, "credit": 0, **common},
                {"account": self.balance_account, "debit": 0, "credit": self.amount, **common},
            ]
        else:
            lines = [
                {"account": self.balance_account, "debit": self.amount, "credit": 0, **common},
                {"account": self.recognition_account, "debit": 0, "credit": self.amount, **common},
            ]
        batch = post_financial_transaction(
            source_doctype=self.doctype, source_name=self.name, posting_date=self.recognition_date,
            currency=self.currency, exchange_rate=self.exchange_rate, lines=lines,
            posting_event="Adjustment", remarks=f"Scheduled recognition for {self.schedule}",
            idempotency_key=f"schedule-recognition:{self.schedule}:{self.period_number}",
        )
        persist_posting_batch_link(self, batch)

    def before_delete(self):
        if self.docstatus == 1:
            throw("A posted Schedule Recognition cannot be deleted.")


def create_purchase_invoice_schedules(invoice):
    """Create approval-pending prepayment schedules for local cost allocations."""
    if not getattr(invoice, "is_amortised_cost", False):
        return []
    created = []
    allocations = list(invoice.cost_allocations or []) if getattr(invoice, "is_shared_cost", False) else [None]
    for line in invoice.lines or []:
        for allocation in allocations:
            if allocation and allocation.allocation_type == "Intercompany":
                continue  # The intercompany outbox carries the amortisation instruction to the receiving entity.
            share = Decimal("1") if allocation is None else Decimal(str(allocation.percentage or 0)) / Decimal("100")
            amount = (Decimal(str(line.amount)) * share).quantize(CENT, rounding=ROUND_HALF_UP)
            if allocation is not None and allocation is allocations[-1]:
                # The final row absorbs rounding residue for each source line.
                prior = sum((Decimal(str(line.amount)) * Decimal(str(a.percentage or 0)) / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
                            for a in allocations[:-1])
                amount = Decimal(str(line.amount)) - prior
            if amount <= 0:
                continue
            cc = (allocation.cost_centre if allocation and allocation.allocation_type == "Cost Centre" else getattr(line, "cost_centre", None))
            bu = (allocation.business_unit if allocation and allocation.allocation_type == "Business Unit" else getattr(line, "business_unit", None))
            schedule = new_doc("Recognition Schedule", schedule_type="Prepayment", source_doctype="Purchase Invoice",
                source_document=invoice.name, source_line=str(getattr(line, "name", "")), start_date=invoice.amortisation_start_date,
                end_date=invoice.amortisation_end_date, frequency=invoice.amortisation_frequency or "Monthly",
                total_amount=amount, balance_account=invoice.prepayment_account, recognition_account=line.account,
                cost_centre=cc or None, business_unit=bu or None, approval_status="Pending",
                notes=f"Generated from Purchase Invoice {invoice.name}; requires independent approval.")
            schedule.insert(ignore_permissions=True)
            # Preserve the original invoice maker as the schedule owner so the
            # person approving the invoice cannot approve the generated schedule.
            if invoice.owner and schedule.owner != invoice.owner:
                schedule.owner = invoice.owner
                schedule.save(ignore_permissions=True)
            created.append(schedule.name)
    return created


def process_due_recognitions(as_of_date=None):
    """Create and post all due schedule periods; safe to rerun daily."""
    as_of_date = as_of_date or date.today()
    schedules = get_list("Recognition Schedule", filters={"docstatus": 1}, fields=["name"], limit=10000, ignore_permissions=True)
    created = []
    for item in schedules:
        schedule = get_doc("Recognition Schedule", item["name"], ignore_permissions=True)
        for period in range(1, int(schedule.period_count) + 1):
            due_date = period_date(schedule.start_date, period, schedule.frequency or "Monthly")
            if schedule.end_date and due_date > schedule.end_date:
                break
            if due_date > as_of_date:
                break
            exists = get_list("Schedule Recognition", filters={"schedule": schedule.name, "period_number": period, "docstatus": 1}, fields=["name"], limit=1, ignore_permissions=True)
            draft = get_list("Schedule Recognition", filters={"schedule": schedule.name, "period_number": period, "docstatus": 0}, fields=["name"], limit=1, ignore_permissions=True)
            if exists:
                continue
            if draft:
                recognition = get_doc("Schedule Recognition", draft[0]["name"], ignore_permissions=True)
            else:
                recognition = new_doc("Schedule Recognition", schedule=schedule.name, period_number=period,
                    recognition_date=due_date, amount=period_amount(schedule.total_amount, int(schedule.period_count), period))
                recognition.insert(ignore_permissions=True)
            recognition.submit(ignore_permissions=True)
            created.append(recognition.name)
    return created
