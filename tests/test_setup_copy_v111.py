"""Copying setup from one running company into another through the platform (the setup is the SAME in a file or a live company)."""
from velora import workflows
from velora.permissions import session_as, Session

from test_platform import H, PW, clean_state, login, plat  # noqa: F401  (fixtures)


def _admin(plat):
    c = plat.client()
    assert login(c, "root@example.com").status_code == 200
    return c


def _define(doctype="Product"):
    return workflows.save_definition({
        "name": "Product Approval", "doctype": doctype, "initial_state": "Draft", "state_field": None,
        "states": [{"name": "Draft"}, {"name": "Approved", "is_final": True}],
        "transitions": [{"action": "Approve", "from_state": "Draft", "to_state": "Approved", "roles": ["Sales Manager"]}]})


def test_a_workflow_is_copied_from_one_company_to_another_and_previewed_first(plat):
    admin = Session("Administrator", frozenset({"System Manager"}))
    with plat.plane.company_scope(plat.A, user_email="Administrator", roles=("System Manager",)):
        _define()
    c = _admin(plat)
    body = {"source_id": plat.A, "sections": ["workflows"]}
    preview = c.post(f"/api/platform/companies/{plat.B}/copy-setup", headers=H, json={**body, "dry_run": True})
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["new"] == 1
    with plat.plane.company_scope(plat.B, user_email="Administrator", roles=("System Manager",)):
        assert workflows.list_definitions() == []                                  # a preview wrote nothing
    done = c.post(f"/api/platform/companies/{plat.B}/copy-setup", headers=H, json=body)
    assert done.status_code == 200, done.text
    with plat.plane.company_scope(plat.B, user_email="Administrator", roles=("System Manager",)):
        assert [w["name"] for w in workflows.list_definitions()] == ["Product Approval"]
    again = c.post(f"/api/platform/companies/{plat.B}/copy-setup", headers=H, json=body)
    assert again.json()["data"]["created"] == 0


def test_copy_setup_needs_two_different_active_companies_and_a_platform_administrator(plat):
    c = _admin(plat)
    assert c.post(f"/api/platform/companies/{plat.A}/copy-setup", headers=H, json={"source_id": plat.A, "sections": ["workflows"]}).status_code == 422
    assert c.post(f"/api/platform/companies/{plat.B}/copy-setup", headers=H, json={"source_id": "NOPE", "sections": ["workflows"]}).status_code == 422
    assert c.post(f"/api/platform/companies/{plat.B}/copy-setup", headers=H, json={"source_id": plat.A, "sections": []}).status_code == 422
    a = plat.client(); login(a, "alice@example.com")
    assert a.post(f"/api/platform/companies/{plat.B}/copy-setup", headers=H, json={"source_id": plat.A, "sections": ["workflows"]}).status_code in (401, 403)
