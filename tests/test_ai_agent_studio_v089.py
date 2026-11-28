from velora import ai_developer as dev
from velora.permissions import Session, session_as
from velora.exceptions import PermissionDenied


def test_agent_studio_persists_role_gated_agents_without_tool_execution(site):
    with session_as(Session("Administrator", frozenset({"AI Developer"}))):
        saved = dev.save_agent({"agent_key":"basic_advisor","title":"Basic Advisor","instructions":"Give careful enterprise advice.","roles":["Finance Manager"],"tools":[]})
        assert saved["enabled"] is True
    with session_as(Session("reader", frozenset({"Accounts User"}))):
        assert not any(x["agent_key"] == "basic_advisor" for x in dev.list_agents())
        try:
            dev.run_agent("basic_advisor", "Help")
        except PermissionDenied:
            pass
        else:
            raise AssertionError("Role-restricted agent was accessible")
