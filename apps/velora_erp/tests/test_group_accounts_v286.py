"""Group accounts are headings; posting accounts are the leaves. Link pickers and validation enforce it."""
import pytest
from velora import new_doc, get_list
from velora.meta.registry import registry
from velora.exceptions import ValidationError, LinkValidationError
from test_inventory_v012 import setup_inventory
from velora_erp.finance.invoices import _account


def acct(code, group, typ, **extra):
    return new_doc("Account", account_code=code, account_name=code, account_group=group, account_type=typ, **extra).insert(ignore_permissions=True)


def test_group_and_posting_accounts(tmp_path):
    item, wh, inventory, grni, cogs, *_ = setup_inventory(tmp_path)
    heading = acct("9000", cogs.account_group, "COST_OF_SALES", is_group=1)
    child = acct("9001", cogs.account_group, "COST_OF_SALES", parent_account=heading.name)
    assert child.parent_account == heading.name and not int(child.is_group or 0)
    with pytest.raises(ValidationError, match="not a group account"):
        acct("9002", cogs.account_group, "COST_OF_SALES", parent_account=cogs.name)          # parent must be a group
    with pytest.raises(ValidationError, match="own parent|itself"):
        heading.parent_account = heading.name
        heading.save(ignore_permissions=True)


def test_group_account_cannot_take_postings_but_a_posting_account_can(tmp_path):
    item, wh, inventory, grni, cogs, *_ = setup_inventory(tmp_path)
    heading = acct("5010", cogs.account_group, "COST_OF_SALES", is_group=1)
    with pytest.raises(ValidationError, match="group account"):
        _account(heading.name, "Expense", "Line 1 Expense Account")
    _account(cogs.name, "Expense", "Line 1 Expense Account")


def test_every_account_link_asks_for_a_posting_account(tmp_path):
    item, wh, inventory, grni, cogs, *_ = setup_inventory(tmp_path)
    heading = acct("9020", cogs.account_group, "COST_OF_SALES", is_group=1)
    seen = 0
    # reports, budgets and corrections may legitimately name a heading or a historic account
    allowed = {"Account Statement Mapping", "Budget Adjustment Line", "Financial Budget Line", "Financial Budget Account", "Account Ledger Record"}
    for dt in registry.all():
        name = dt.name
        for f in registry.get(name).fields:
            if f.fieldtype == "Link" and f.options == "Account" and name != "Account":
                seen += 1
                if f.fieldname.endswith("parent_account") or name in allowed:
                    continue
                assert [list(r) for r in f.link_filters][:1] == [["is_group", "=", 0]], f"{name}.{f.fieldname}"
    assert seen > 100
    pool = get_list("Account", filters=[["is_group", "=", 0]], ignore_permissions=True)
    assert heading.name not in [a["name"] for a in pool] and cogs.name in [a["name"] for a in pool]


def test_search_pseudo_filter_matches_any_text_column(tmp_path):
    item, wh, inventory, grni, cogs, *_ = setup_inventory(tmp_path)
    hit = get_list("Account", filters=[["_search", "like", "Cost of Goods"]], ignore_permissions=True)
    assert cogs.name in [a["name"] for a in hit]
    assert get_list("Account", filters=[["_search", "like", "zzzznothing"]], ignore_permissions=True) == []


def test_search_ignores_the_percent_wrapping_the_list_bar_adds(tmp_path):
    item, wh, inventory, grni, cogs, *_ = setup_inventory(tmp_path)
    hit = get_list("Account", filters=[["_search", "like", "%cost of goods%"]], ignore_permissions=True)
    assert cogs.name in [a["name"] for a in hit]
