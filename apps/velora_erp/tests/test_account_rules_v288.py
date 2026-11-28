"""A control account is a posting account; a group is only a heading. The messages say so in plain words."""
import pytest
from velora import new_doc
from velora.exceptions import ValidationError
from test_cash_transactions import setup_cash


def test_group_account_cannot_be_a_control_account_and_the_message_explains(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    heading = new_doc("Account", account_code="1900", account_name="Receivables Heading", account_group="A", account_type="RECEIVABLE", is_group=1).insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match=r"group \(heading\) account.*Choose a posting account"):
        new_doc("Customer", customer_code="C777", customer_name="Group Test", customer_group="CG", customer_type="Company",
                control_account=heading.name, advance_account=accounts["2200"].name).insert(ignore_permissions=True)
    assert (heading.is_control_account, heading.requires_party, heading.reconciliation_required) == (0, 0, 0)      # a heading never carries posting settings
    ticked = new_doc("Account", account_code="1901", account_name="Ticked Group", account_group="A", account_type="RECEIVABLE", is_group=1,
                     is_control_account=1, control_account_type="Receivables").insert(ignore_permissions=True)
    assert (ticked.is_control_account, ticked.control_account_type) == (0, None)                              # ticking Group clears them instead of refusing
    ok = new_doc("Customer", customer_code="C778", customer_name="Posting Test", customer_group="CG", customer_type="Company",
                 control_account=accounts["1100"].name, advance_account=accounts["2200"].name).insert(ignore_permissions=True)
    assert ok.control_account == accounts["1100"].name
