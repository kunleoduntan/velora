from sqlalchemy import func, select

from velora import Document, db, throw
from velora.db.tables import get_table

from .... import common as c

ROOT_FOR = {"Bank": "Asset", "Cash": "Asset", "Receivable": "Asset", "Fixed Asset": "Asset", "Accumulated Depreciation": "Asset", "Stock": "Asset",
            "Payable": "Liability", "Retained Earnings": "Equity", "Cost of Sales": "Expense"}


def _row(name):
    t = get_table("Account")
    with db.transaction() as conn:
        r = conn.execute(select(t.c.name, t.c.parent_account, t.c.root_type, t.c.is_group, t.c.account_type).where(t.c.name == name)).mappings().first()
    return dict(r) if r else None


def has_entries(name) -> bool:
    g = get_table("GL Entry")
    with db.transaction() as conn:
        return conn.execute(select(func.count()).select_from(g).where(g.c.account == name)).scalar() > 0


class Account(Document):
    def validate(self):
        self.account_name = (self.account_name or "").strip()
        if not self.account_name:
            throw("Account name is required")
        parent = None
        if self.parent_account:
            if self.parent_account == self.name or self.parent_account == self.account_name:
                throw("An account cannot be its own parent")
            parent = _row(self.parent_account)
            if parent is None:
                throw(f"Parent account {self.parent_account!r} does not exist")
            if not parent["is_group"]:
                throw(f"{self.parent_account} is not a group account, so it cannot have sub-accounts")
            seen, cur = set(), parent
            while cur:                                         # no cycles: walk up to the root
                if cur["name"] in seen or cur["name"] == self.account_name:
                    throw("That parent would create a loop in the chart of accounts")
                seen.add(cur["name"])
                cur = _row(cur["parent_account"]) if cur["parent_account"] else None
            if self.root_type and self.root_type != parent["root_type"]:
                throw(f"Root type must match the parent ({parent['root_type']})")
            self.root_type = parent["root_type"]
        elif not self.root_type:
            throw("A top-level account needs a root type (Asset, Liability, Equity, Income or Expense)")
        if self.is_group and self.account_type:
            throw("A group account cannot have an account type; set it on the sub-accounts")
        need = ROOT_FOR.get(self.account_type or "")
        if need and need != self.root_type:
            throw(f"A {self.account_type} account must sit under {need}s")
        if self.account_number:
            t = get_table("Account")
            with db.transaction() as conn:
                dup = conn.execute(select(t.c.name).where(t.c.account_number == self.account_number, t.c.name != (self.name or ""))).first()
            if dup:
                throw(f"Account number {self.account_number} is already used by {dup[0]}")
        old = self._old
        if old and has_entries(self.name):
            for f in ("root_type", "is_group", "account_type", "parent_account"):
                if (old.get(f) or None) != (self.get(f) or None) and not (f == "is_group" and not old.get(f) and not self.get(f)):
                    throw(f"{self.name} already has ledger entries, so its {f.replace('_', ' ')} cannot be changed")

    def before_delete(self):
        if has_entries(self.name):
            throw(f"{self.name} has ledger entries and cannot be deleted; disable it instead")
        t = get_table("Account")
        with db.transaction() as conn:
            if conn.execute(select(t.c.name).where(t.c.parent_account == self.name).limit(1)).first():
                throw(f"{self.name} has sub-accounts and cannot be deleted")
        if self.name in (c.get_default(k, required=False) for k in c.DEFAULT_KINDS):
            throw(f"{self.name} is a default account; choose another default first")
