"""Database-backed validation helpers for Finance master data."""
from sqlalchemy import select
from velora.db.tables import get_table
from velora import db, throw


def row(doctype: str, name: str, *columns: str):
    if not name:
        return None
    table = get_table(doctype)
    selected = [table.c[c] for c in columns] if columns else [table.c.name]
    with db.transaction() as conn:
        result = conn.execute(select(*selected).where(table.c.name == name)).mappings().first()
    return dict(result) if result else None


def assert_parent(doctype: str, parent_name: str, *, self_name: str, group_field: str, root_field: str | None = None, expected_root: str | None = None):
    if not parent_name:
        return None
    if parent_name == self_name:
        throw(f"A {doctype.lower()} cannot be its own parent")
    parent_field = {"Account Group": "parent_group", "Cost Centre": "parent_cost_centre", "Dimension Value": "parent_value", "Financial Statement Row": "parent_row"}.get(doctype)
    selected = ["name", group_field] + ([parent_field] if parent_field else []) + ([root_field] if root_field else [])
    parent = row(doctype, parent_name, *selected)
    if not parent:
        throw(f"Parent {doctype.lower()} {parent_name!r} does not exist")
    if not parent[group_field]:
        throw(f"{parent_name} is not a group and cannot contain children")
    if root_field and expected_root and parent[root_field] != expected_root:
        throw(f"Financial class must match the parent ({parent[root_field]})")
    seen = set()
    current = parent
    while current:
        if current["name"] in seen or current["name"] == self_name:
            throw("This parent would create a hierarchy loop")
        seen.add(current["name"])
        p = current.get(parent_field) if parent_field else None
        current = row(doctype, p, *selected) if p else None
    return parent


def assert_unique(doctype: str, fieldname: str, value: str, current_name: str | None = None):
    table = get_table(doctype)
    with db.transaction() as conn:
        found = conn.execute(select(table.c.name).where(table.c[fieldname] == value, table.c.name != (current_name or "")).limit(1)).first()
    if found:
        throw(f"{fieldname.replace('_', ' ').title()} {value!r} is already used by {found[0]}")


def assert_no_children(doctype: str, fieldname: str, name: str, label: str):
    table = get_table(doctype)
    with db.transaction() as conn:
        found = conn.execute(select(table.c.name).where(table.c[fieldname] == name).limit(1)).first()
    if found:
        throw(f"{label} has child records and cannot be deleted")


def check_control_account(name, root_type: str, purpose: str, what: str) -> None:
    """Say exactly why an account cannot be this party's control account (receivables for customers, payables for suppliers)."""
    from velora import throw
    acct = row("Account", name, "name", "root_type", "is_group", "is_control_account", "control_account_type", "disabled")
    if not acct:
        throw(f"{what}: account {name!r} does not exist.")
    if acct["is_group"]:
        throw(f"{what}: account {name} is a group (heading) account, which only adds up the accounts under it. Choose a posting account (not a group) - one of its sub-accounts.")
    if acct["disabled"]:
        throw(f"{what}: account {name} is disabled. Enable it or choose another.")
    if acct["root_type"] != root_type:
        throw(f"{what}: account {name} is a {acct['root_type']} account; it must be an {root_type} account." if root_type == "Asset" else f"{what}: account {name} is a {acct['root_type']} account; it must be a {root_type} account.")
    if not acct["is_control_account"] or acct["control_account_type"] != purpose:
        throw(f"{what}: account {name} is not a {purpose} control account. Open the account, tick Control Account and set its purpose to {purpose}.")
