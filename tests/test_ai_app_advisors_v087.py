import importlib
from velora import ai
from velora.meta.registry import registry
from velora.permissions import Session, session_as


def test_veloraerp_app_exposes_declared_advisors(site):
    hooks=importlib.import_module("velora_erp.hooks")
    if "velora_erp" not in registry._apps:
        registry._apps.append("velora_erp")
    try:
        advisors=ai.discover_advisors()
        ids={a["id"] for a in advisors}
        assert "veloraerp.finance.advisor" in ids
        assert "veloraerp.sales.invoice.reviewer" in ids
    finally:
        if "velora_erp" in registry._apps:
            registry._apps.remove("velora_erp")


def test_advisor_role_visibility(site):
    ai.register_advisor({"id":"test.only.finance","title":"Finance only","roles":["Finance Manager"]})
    with session_as(Session("staff",frozenset({"Accounts User"}))):
        assert "test.only.finance" not in {a["id"] for a in ai.list_advisors()}
    with session_as(Session("manager",frozenset({"Finance Manager"}))):
        assert "test.only.finance" in {a["id"] for a in ai.list_advisors()}
