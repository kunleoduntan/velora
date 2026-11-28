"""A role that fills in documents can pick from the masters those documents link to, even when it cannot open the master's own list."""
import pytest

import velora
from velora import new_doc
from velora.api.search import search_link
from velora.exceptions import PermissionDenied
from velora.meta.spec import DocPerm
from velora.permissions import Session, session_as


@pytest.fixture()
def site(tmp_path):
    velora.init(velora.configure(db_url=f"sqlite:///{tmp_path / 'p.db'}", apps=["velora_demo"], developer_mode=True))
    velora.migrate()
    yield
    velora.shutdown()


def test_picking_follows_the_documents_the_role_can_fill_in(site):
    from velora.meta.registry import registry
    new_doc("Customer Group", group_name="Retail").insert(ignore_permissions=True)
    clerk = Session(user="clerk", roles=frozenset({"Order Clerk"}))
    with session_as(clerk):
        with pytest.raises(PermissionDenied):
            search_link("Customer Group", "ret")                    # nothing links to it that this role can fill in
    registry.get("Customer").permissions.append(DocPerm(role="Order Clerk", read=True, write=True, create=True))
    try:
        with session_as(clerk):
            rows = search_link("Customer Group", "ret")
        assert [r["name"] for r in rows] == ["Retail"]
        with session_as(Session(user="nobody", roles=frozenset({"Other"}))):
            with pytest.raises(PermissionDenied):
                search_link("Customer Group", "ret")
    finally:
        registry.get("Customer").permissions.pop()
