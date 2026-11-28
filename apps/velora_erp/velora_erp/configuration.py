"""VeloraERP governed configuration catalogue and company setup readiness.

Legacy settings DocTypes remain the operational source until each domain is
explicitly migrated. Published governed settings override legacy values only
for keys with a registered binding; no silent mass migration occurs.
"""
from __future__ import annotations

from velora import get_list
from velora.exceptions import ValidationError, DoesNotExistError

# key, title, domain, type, legacy doctype, legacy field, risk, required
_BINDINGS = [
    ("finance.allow_backdated_posting", "Allow Backdated Posting", "finance", "boolean", "Finance Settings", "allow_backdated_posting", "high", False),
    ("finance.backdated_posting_days", "Maximum Backdating Days", "finance", "integer", "Finance Settings", "backdated_posting_days", "elevated", False),
    ("finance.prevent_posting_to_closed_periods", "Prevent Posting to Closed Periods", "finance", "boolean", "Finance Settings", "prevent_posting_to_closed_periods", "critical", False),
    ("inventory.default_asset_account", "Default Inventory Asset Account", "inventory", "string", "Inventory Settings", "default_inventory_asset_account", "critical", True),
    ("inventory.grni_account", "Goods Received Not Invoiced Account", "inventory", "string", "Inventory Settings", "goods_received_not_invoiced_account", "critical", True),
    ("inventory.cogs_account", "Cost of Goods Sold Account", "inventory", "string", "Inventory Settings", "cost_of_goods_sold_account", "critical", True),
    ("inventory.block_below_cost", "Block Selling Below Cost", "inventory", "boolean", "Inventory Settings", "block_selling_below_cost", "high", False),
    ("inventory.require_cost", "Require Cost Before Stock Sales", "inventory", "boolean", "Inventory Settings", "require_cost_for_stock_sales", "high", False),
    ("inventory.allow_manual_price", "Allow Manual Selling Price", "sales", "boolean", "Inventory Settings", "allow_manual_selling_price", "elevated", False),
    ("inventory.default_margin_percent", "Default Selling Margin", "sales", "decimal", "Inventory Settings", "default_selling_margin_percent", "elevated", False),
    ("inventory.selling_cost_basis", "Selling Cost Basis", "inventory", "string", "Inventory Settings", "selling_cost_basis", "high", False),
    ("inventory.minimum_profit_percent", "Minimum Profit", "sales", "decimal", "Inventory Settings", "minimum_profit_percent", "high", False),
    ("inventory.selling_price_basis", "Selling Price Basis", "sales", "string", "Inventory Settings", "selling_price_basis", "elevated", False),
 ]

# These identity/structural contracts are deliberately catalogue-only. They
# must not override active accounting identity until a dedicated migration
# service validates existing ledgers, periods and tax registrations.
_UNBOUND_DEFINITIONS = [
    ("finance.base_currency", "Base Currency", "finance", "string", "critical", True),
    ("finance.country_code", "Country Code", "localisation", "string", "high", True),
    ("finance.accounting_basis", "Accounting Basis", "finance", "string", "high", True),
    ("finance.accounting_framework", "Accounting Framework", "finance", "string", "high", True),
    ("finance.financial_year_start_month", "Financial Year Start Month", "finance", "string", "critical", True),
    ("finance.decimal_places", "Currency Decimal Places", "finance", "integer", "critical", True),
]


def seed_settings_catalogue():
    """Idempotently register contracts in one transaction; never overwrite values."""
    from sqlalchemy import insert, select
    from velora import db
    from velora.settings_governance import ensure, catalogue, _audit, _now, _admin
    actor = _admin().user
    ensure()
    created = 0
    now = _now()
    with db.transaction() as conn:
        definitions = [(key, title, domain, value_type, risk, required, True)
                       for key, title, domain, value_type, _doctype, _field, risk, required in _BINDINGS]
        definitions += [(key, title, domain, value_type, risk, required, False)
                        for key, title, domain, value_type, risk, required in _UNBOUND_DEFINITIONS]
        for key, title, domain, value_type, risk, required, operational in definitions:
            exists = conn.execute(select(catalogue.c.name).where(catalogue.c.name == key)).first()
            if exists:
                continue
            description = (f"Company-scoped {title.lower()} policy. Published values override the legacy field only through an explicit operational binding."
                           if operational else f"Company-scoped {title.lower()} policy. Structural setting: requires a dedicated migration workflow before it may affect live operations.")
            conn.execute(insert(catalogue).values(
                name=key, title=title, description=description,
                domain=domain, value_type=value_type, allowed_scopes=["legal_entity"],
                fallback_scopes=[], default_value=None, required=int(required), risk=risk,
                secret=0, active=1, created_by=actor, created_on=now,
            ))
            _audit(conn, key, None, "definition_created", actor,
                   {"domain": domain, "risk": risk, "allowed_scopes": ["legal_entity"], "seeded_by": "VeloraERP", "operational_binding": operational})
            created += 1
    return created


def apply_governed_settings(doctype: str, settings: dict) -> dict:
    """Apply published governed overrides with one indexed query per settings load."""
    from datetime import date
    from sqlalchemy import select
    from velora import db
    from velora.settings_governance import ensure, versions
    result = dict(settings or {})
    bindings = [(key, field) for key, _title, _domain, _typ, bound_doctype, field, _risk, _required in _BINDINGS
                if bound_doctype == doctype and field in result]
    if not bindings:
        return result
    keys = [key for key, _field in bindings]
    ensure()
    with db.transaction() as conn:
        rows = conn.execute(select(versions.c.setting, versions.c.value, versions.c.effective_from, versions.c.version)
            .where(versions.c.setting.in_(keys), versions.c.scope_type == "legal_entity",
                   versions.c.scope_key == "", versions.c.effective_from <= date.today())
            .order_by(versions.c.setting, versions.c.effective_from.desc(), versions.c.version.desc())).mappings().all()
    latest = {}
    for row in rows:
        latest.setdefault(row["setting"], row["value"])
    for key, field in bindings:
        if key in latest:
            result[field] = latest[key]
    return result


def _count(doctype: str, filters=None) -> int:
    try:
        from velora import get_count
        return int(get_count(doctype, filters=filters or {}, ignore_permissions=True))
    except Exception:
        return 0


def setup_readiness() -> dict:
    """Assess operational readiness from actual company records, not assumptions."""
    checks = []
    def add(code, title, category, passed, detail, severity="blocking"):
        checks.append({"code": code, "title": title, "category": category,
                       "status": "complete" if passed else ("attention" if severity == "warning" else "incomplete"),
                       "severity": severity, "detail": detail})

    finance = get_list("Finance Settings", fields=["name", "base_currency", "country_code", "financial_year_start_month"], limit=1, ignore_permissions=True)
    add("FINANCE_SETTINGS", "Finance Settings", "Finance", bool(finance and finance[0].get("base_currency") and finance[0].get("country_code")),
        "Company currency and country are configured." if finance else "Create and complete Finance Settings.")
    inventory = get_list("Inventory Settings", fields=["name", "default_inventory_asset_account", "goods_received_not_invoiced_account", "cost_of_goods_sold_account", "stock_adjustment_gain_account", "stock_adjustment_loss_account"], limit=1, ignore_permissions=True)
    inv_ok = bool(inventory and all(inventory[0].get(k) for k in ("default_inventory_asset_account", "goods_received_not_invoiced_account", "cost_of_goods_sold_account", "stock_adjustment_gain_account", "stock_adjustment_loss_account")))
    add("INVENTORY_SETTINGS", "Inventory Accounting Settings", "Inventory", inv_ok,
        "Required inventory control accounts are configured." if inv_ok else "Configure Inventory Asset, GRNI, COGS and stock adjustment accounts.")
    years = _count("Financial Year")
    add("FINANCIAL_YEAR", "Financial Year", "Finance", years > 0,
        f"{years} financial year record(s) found." if years else "Create the legal entity's financial year calendar.")
    accounts = _count("Account")
    add("CHART_OF_ACCOUNTS", "Chart of Accounts", "Finance", accounts > 0,
        f"{accounts} account record(s) found." if accounts else "Import or create the company's chart of accounts.")
    periods = _count("Financial Period")
    add("FINANCIAL_PERIODS", "Financial Periods", "Finance", periods > 0,
        f"{periods} financial period record(s) found." if periods else "Create financial periods for the active financial year.")
    customer_count = _count("Customer")
    supplier_count = _count("Supplier")
    warehouse_count = _count("Warehouse")
    add("CUSTOMER_MASTER", "Customer Master", "Sales", customer_count > 0,
        f"{customer_count} customer record(s) found." if customer_count else "Create customer records before processing receivables.", "warning")
    add("SUPPLIER_MASTER", "Supplier Master", "Purchasing", supplier_count > 0,
        f"{supplier_count} supplier record(s) found." if supplier_count else "Create supplier records before processing payables.", "warning")
    add("WAREHOUSE_MASTER", "Warehouse Master", "Inventory", warehouse_count > 0,
        f"{warehouse_count} warehouse record(s) found." if warehouse_count else "Create warehouses before stock transactions.", "warning")
    blocking = sum(1 for x in checks if x["severity"] == "blocking" and x["status"] != "complete")
    warnings = sum(1 for x in checks if x["severity"] == "warning" and x["status"] != "complete")
    return {"status": "ready" if blocking == 0 else "setup_required", "score": round(100 * sum(x["status"] == "complete" for x in checks) / max(1, len(checks))),
            "completed": sum(x["status"] == "complete" for x in checks), "total": len(checks),
            "blocking_issues": blocking, "warnings": warnings, "checks": checks}
