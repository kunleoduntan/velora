"""The upgrade patch empties authority lists that still equal the old built-in roles, and keeps a company's own choices."""
import pytest

import velora
from velora_erp.finance import approval_authority as aa
from velora_erp.patches.v2_87 import release_old_default_authority as patch


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'p.db'}", apps=[], developer_mode=True)
    velora.init(); velora.migrate()


def test_old_default_roles_are_released_but_custom_ones_stay(site):
    aa.set_authority("budget.override", ["Finance Manager", "System Manager"])     # exactly the old built-in list
    aa.set_authority("hr_policy.approve", ["Auditor"])                     # the company's own choice
    patch.execute()
    assert aa.roles_for("budget.override") == ()
    assert aa.roles_for("hr_policy.approve") == ("Auditor",)
    patch.execute()                                                                 # safe to run twice
    assert aa.roles_for("hr_policy.approve") == ("Auditor",)
