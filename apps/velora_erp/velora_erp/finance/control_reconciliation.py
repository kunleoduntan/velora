"""Common read-only reconciliation calculations for Finance control accounts.

The module compares independently maintained operational subledgers with the
immutable Account Ledger. It never creates journals or adjusts either balance.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib


class ControlReconciliationError(ValueError):
    pass


SUPPORTED_CONTROLS = {
    "Receivables", "Payables", "Inventory", "Fixed Assets", "Employee Loans",
    "Employee Advances", "Payroll Liabilities", "Tax Liabilities", "Pension Liabilities",
}


def _decimal(value, label):
    try:
        amount = Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ControlReconciliationError(f"{label} must be numeric") from exc
    if not amount.is_finite():
        raise ControlReconciliationError(f"{label} must be finite")
    return amount


def reconcile_control(*, control_type, control_account, gl_balance, source_balances,
                      tolerance="0.01", as_of_date=None, currency=None):
    """Reconcile one control account and return a deterministic review snapshot.

    Source balances are signed in the same debit-positive convention as the GL.
    Duplicate source references are rejected so a caller cannot accidentally
    double-count a document while assembling the subledger population.
    """
    if control_type not in SUPPORTED_CONTROLS:
        raise ControlReconciliationError("Unsupported control type")
    if not str(control_account or "").strip():
        raise ControlReconciliationError("Control Account is required")
    if not isinstance(source_balances, (list, tuple)):
        raise ControlReconciliationError("Source balances must be a list")

    gl = _decimal(gl_balance, "GL balance")
    tol = _decimal(tolerance, "Tolerance")
    if tol < 0:
        raise ControlReconciliationError("Tolerance cannot be negative")

    total = Decimal("0")
    details = []
    seen = set()
    for row in source_balances:
        if not isinstance(row, dict):
            raise ControlReconciliationError("Every source balance must be an object")
        source_type = str(row.get("source_type") or "").strip()
        source_name = str(row.get("source_name") or "").strip()
        if not source_type or not source_name:
            raise ControlReconciliationError("Every source balance requires source type and source name")
        key = (source_type, source_name)
        if key in seen:
            raise ControlReconciliationError(f"Duplicate source balance: {source_type} {source_name}")
        seen.add(key)
        row_currency = row.get("currency")
        if currency and row_currency and str(row_currency).upper() != str(currency).upper():
            raise ControlReconciliationError("Source balance currency mismatch")
        amount = _decimal(row.get("balance"), "Source balance")
        total += amount
        details.append({"source_type": source_type, "source_name": source_name,
                        "balance": amount, "currency": row_currency or currency})

    difference = total - gl
    matched = abs(difference) <= tol
    identity = "|".join((str(control_type), str(control_account), str(currency or ""),
                         str(as_of_date or "Current")))
    reconciliation_id = "CTRL-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
    return {
        "reconciliation_id": reconciliation_id,
        "control_type": control_type,
        "control_account": control_account,
        "currency": currency,
        "as_of_date": as_of_date or "Current",
        "source_balance": total,
        "gl_balance": gl,
        "difference": difference,
        "tolerance": tol,
        "status": "Reconciled" if matched else "Exception",
        "details": details,
        "exception_required": not matched,
        "requires_review": True,
        "automatic_journal": False,
        "read_only": True,
    }


def build_control_reconciliation_exception(result):
    """Build an actionable exception record without creating a journal."""
    if not result.get("exception_required"):
        return None
    return {
        "exception_id": result["reconciliation_id"],
        "exception_type": f"{result['control_type']} Control Account Difference",
        "control_account": result["control_account"],
        "currency": result.get("currency"),
        "as_of_date": result.get("as_of_date"),
        "source_balance": result["source_balance"],
        "gl_balance": result["gl_balance"],
        "difference": result["difference"],
        "status": "Open",
        "resolution_required": True,
        "journal_created": False,
        "automatic_adjustment": False,
    }


def build_control_reconciliation_pack(*, company, as_of_date, reconciliations, prepared_by):
    """Aggregate account reconciliations into a review/period-close control pack."""
    if not company or not as_of_date or not prepared_by:
        raise ControlReconciliationError("Company, as-of date and preparer are required")
    if not isinstance(reconciliations, list) or not reconciliations:
        raise ControlReconciliationError("At least one reconciliation is required")
    ids = [row.get("reconciliation_id") for row in reconciliations]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ControlReconciliationError("Every reconciliation must have a unique reconciliation ID")
    exceptions = [build_control_reconciliation_exception(row) for row in reconciliations]
    exceptions = [row for row in exceptions if row]
    return {
        "company": company,
        "as_of_date": str(as_of_date),
        "prepared_by": prepared_by,
        "status": "Ready for Review" if not exceptions else "Exceptions Outstanding",
        "reconciliation_count": len(reconciliations),
        "reconciled_count": len(reconciliations) - len(exceptions),
        "exception_count": len(exceptions),
        "reconciliations": reconciliations,
        "exceptions": exceptions,
        "publication_blockers": [x["exception_id"] for x in exceptions],
        "read_only": True,
        "posting_side_effects": False,
    }
