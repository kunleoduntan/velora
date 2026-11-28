from datetime import date
from decimal import Decimal
import hashlib
import json

from sqlalchemy import func, select

from velora import Document, db, get_doc, get_list, throw
from velora.db.tables import get_table
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, approval_required

CHECKLIST = [
    ("BANK_RECON", "All bank and cash accounts have been reconciled."),
    ("AR_RECON", "Accounts receivable subledger agrees to the general ledger."),
    ("AP_RECON", "Accounts payable subledger agrees to the general ledger."),
    ("INVENTORY", "Inventory quantities and valuation have been reviewed and reconciled."),
    ("FIXED_ASSETS", "Fixed asset additions, disposals, depreciation and impairment have been reviewed."),
    ("TAX", "Current tax and deferred tax calculations have been reviewed."),
    ("ACCRUALS", "Accruals, prepayments and period-end adjustments have been reviewed."),
    ("SUSPENSE", "Suspense, clearing and control accounts have been investigated."),
    ("REVENUE_EXPENSE", "Revenue and expense cut-off has been reviewed."),
    ("DISCLOSURES", "Required period-end supporting schedules and disclosures are available."),
]


def _period(name):
    period = get_doc("Financial Period", name, ignore_permissions=True)
    if not period:
        throw("Select a valid Financial Period.")
    return period


def _automated_controls(period):
    ledger = get_table("Account Ledger Record")
    with db.transaction() as conn:
        totals = conn.execute(
            select(
                func.coalesce(func.sum(ledger.c.base_debit), 0),
                func.coalesce(func.sum(ledger.c.base_credit), 0),
            ).where(ledger.c.posting_date <= period.end_date)
        ).first()
    difference = abs(Decimal(str(totals[0] or 0)) - Decimal(str(totals[1] or 0)))
    pending = get_list(
        "Deferred Tax Posting Inbox",
        filters=[["posting_date", ">=", period.start_date], ["posting_date", "<=", period.end_date], ["status", "in", ["Pending Review", "Approved"]]],
        fields=["name"], limit=10000, ignore_permissions=True,
    )
    return difference, len(pending)


class FinancialPeriodClose(Document):
    def validate(self):
        validate_approval_transition(self)
        if not self.financial_period or not self.close_date:
            throw("Financial Period and Close Date are required.")
        period = _period(self.financial_period)
        self.financial_year = period.financial_year
        if period.status == "Closed":
            if getattr(self, "docstatus", 0) != 1:
                throw("This Financial Period is already closed.")
        elif period.status not in ("Open", "Closing"):
            throw("Only an Open or Closing Financial Period can be closed.")
        if str(self.close_date) < str(period.end_date):
            throw("Close Date cannot be earlier than the Financial Period end date.")
        existing = get_list("Financial Period Close", filters=[["financial_period", "=", self.financial_period], ["docstatus", "=", 1]], fields=["name"], limit=5, ignore_permissions=True)
        if existing and existing[0]["name"] != self.name:
            throw(f"Financial Period {self.financial_period} already has a submitted close record.")
        if not self.checklist:
            self.checklist = [{"item_code": code, "description": description, "completed": 0} for code, description in CHECKLIST]
        expected = {code: description for code, description in CHECKLIST}
        codes = [line.item_code for line in self.checklist]
        actual = set(codes)
        missing = set(expected) - actual
        unknown = actual - set(expected)
        duplicates = sorted({code for code in codes if codes.count(code) > 1})
        if missing or unknown or duplicates:
            details = []
            if missing: details.append("missing " + ", ".join(sorted(missing)))
            if unknown: details.append("unsupported " + ", ".join(sorted(unknown)))
            if duplicates: details.append("duplicate " + ", ".join(duplicates))
            throw("Invalid period close checklist: " + "; ".join(details))
        for line in self.checklist:
            if line.description != expected[line.item_code]:
                throw(f"Checklist description for {line.item_code} is system-controlled and cannot be changed.")
        self.trial_balance_difference, self.unresolved_deferred_tax_proposals = _automated_controls(period)
        self.system_checks_passed = int(self.trial_balance_difference == 0 and self.unresolved_deferred_tax_proposals == 0)
        snapshot = {
            "financial_period": self.financial_period,
            "close_date": str(self.close_date),
            "close_notes": self.close_notes or "",
            "checklist": [
                {"item_code": line.item_code, "description": line.description,
                 "completed": bool(line.completed), "evidence_reference": line.evidence_reference or "",
                 "reviewer_notes": line.reviewer_notes or ""}
                for line in self.checklist
            ],
            "trial_balance_difference": str(self.trial_balance_difference),
            "unresolved_deferred_tax_proposals": int(self.unresolved_deferred_tax_proposals or 0),
        }
        fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        old = getattr(self, "_old", None) or {}
        if approval_required(self.doctype) and old.get("approval_status") == "Approved" and self.approval_status == "Approved":
            if old.get("approval_hash") != fingerprint or self.approval_hash != fingerprint:
                throw("An approved period close is immutable. An authorised manager must reset approval before changing its checklist or close evidence.")
        elif self.approval_status == "Approved":
            self.approval_hash = fingerprint
        else:
            self.approval_hash = None
        if self.approval_status == "Approved":
            self.status = "Approved"
        elif self.approval_status == "Rejected":
            self.status = "Rejected"
        else:
            self.status = "Draft"

    def before_submit(self):
        ensure_approved(self, required=True)
        if not self.system_checks_passed:
            throw("Automated period-end controls have not passed. Resolve the trial balance difference and deferred tax proposals before closing.")
        incomplete = [line.item_code for line in self.checklist if not line.completed]
        if incomplete:
            throw("Complete every period-end review checklist item before closing: " + ", ".join(incomplete))
        undocumented = [line.item_code for line in self.checklist if not (line.reviewer_notes or "").strip()]
        if undocumented:
            throw("Reviewer Notes are required for every completed checklist item: " + ", ".join(undocumented))
        if any(not line.evidence_reference and line.item_code in {"BANK_RECON", "AR_RECON", "AP_RECON", "INVENTORY", "FIXED_ASSETS", "TAX"} for line in self.checklist):
            throw("Evidence references are required for bank, receivables, payables, inventory, fixed asset and tax reconciliations.")
        period = _period(self.financial_period)
        if period.status == "Closed":
            throw("This Financial Period is already closed.")

    def on_submit(self):
        period = _period(self.financial_period)
        db_update(period, status="Closed", closed_on=self.close_date, close_notes=self.close_notes or f"Closed through {self.name}")
        db_update(self, status="Closed")

def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted period close record is retained for audit.")
