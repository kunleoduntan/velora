import pytest
from velora_projectone.projectone.services.project_finance_commands import ProjectFinanceCommandService
from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor


class Repository:
    def __init__(self): self.rows = {}; self.counter = 0
    def insert(self, actor, doctype, document, *, idempotency_key, trusted_fields=None):
        self.counter += 1
        row = dict(document, **(trusted_fields or {}), name=f"{doctype}-{self.counter}", owner=actor.actor_id)
        if doctype == "Project Performance Obligation": row.setdefault("status", "Draft")
        if doctype == "Project Revenue Recognition": row.setdefault("approval_status", "Pending Review")
        self.rows[(doctype, row["name"])] = row
        return row
    def get(self, actor, doctype, name): return self.rows.get((doctype, name))

class Bridge:
    def __init__(self): self.repo = Repository(); self.actions=[]
    def document_repository(self): return self.repo
    def assert_permission(self, actor, permission, *, project_id=None):
        if actor.company_id != "C-1": raise PermissionError()
    def workflow_action(self, actor, doctype, name, action, evidence=None):
        self.actions.append((doctype, name, action, evidence))
        return {"workflow": {"status": "submitted"}}

class Sources:
    def get_recognition_inputs(self, actor, *, obligation, period_end):
        return {"project":"P-1", "currency":"NGN", "source_watermark":"ERP:2026-11-30:rev-7",
                "cumulative_actual_cost":250, "forecast_total_cost":500,
                "prior_cumulative_revenue":0, "prior_cumulative_cost":0,
                "current_period_cost":250}


def approved_obligation(service, actor):
    row = service.create_performance_obligation(actor, {
        "project":"P-1", "contract_reference":"CTR-1",
        "obligation_code":"PO-1", "description":"Delivery services",
        "currency":"NGN", "allocated_transaction_price":1000,
        "recognition_method":"cost_to_cost", "recognition_over_time":True,
        "accounting_conclusion_reference":"FIN-APPROVAL-1",
    }, idempotency_key="po-1")
    row["status"] = "Approved"
    service.repository.rows[("Project Performance Obligation", row["name"])]["status"] = "Approved"
    return row


def test_recognition_proposal_uses_host_source_not_client_cost_values():
    bridge = Bridge(); actor = AuthenticatedActor("U-1", "C-1", frozenset())
    service = ProjectFinanceCommandService(bridge, recognition_source_provider=Sources())
    obligation = approved_obligation(service, actor)
    result = service.create_recognition_proposal(actor, obligation_name=obligation["name"],
                                                 period_end="2026-11-30", idempotency_key="rr-1")
    assert result["current_period_revenue"] == 500
    assert result["cumulative_profit"] == 250
    assert result["approval_status"] == "Pending Review"
    assert result["source_watermark"] == "ERP:2026-11-30:rev-7"


def test_recognition_proposal_rejects_source_currency_mismatch():
    class BadCurrency(Sources):
        def get_recognition_inputs(self, actor, *, obligation, period_end):
            data = super().get_recognition_inputs(actor, obligation=obligation, period_end=period_end)
            data["currency"] = "USD"
            return data
    bridge = Bridge(); actor = AuthenticatedActor("U-1", "C-1", frozenset())
    service = ProjectFinanceCommandService(bridge, recognition_source_provider=BadCurrency())
    obligation = approved_obligation(service, actor)
    with pytest.raises(ValueError, match="currency must match"):
        service.create_recognition_proposal(actor, obligation_name=obligation["name"],
                                            period_end="2026-11-30", idempotency_key="rr-4")


def test_recognition_proposal_fails_closed_without_authoritative_provider():
    bridge = Bridge(); actor = AuthenticatedActor("U-1", "C-1", frozenset())
    service = ProjectFinanceCommandService(bridge)
    obligation = approved_obligation(service, actor)
    with pytest.raises(RuntimeError, match="source provider is not configured"):
        service.create_recognition_proposal(actor, obligation_name=obligation["name"],
                                            period_end="2026-11-30", idempotency_key="rr-2")


def test_recognition_proposal_rejects_source_data_for_another_project():
    class BadSources(Sources):
        def get_recognition_inputs(self, actor, *, obligation, period_end):
            data = super().get_recognition_inputs(actor, obligation=obligation, period_end=period_end)
            data["project"] = "P-2"
            return data
    bridge = Bridge(); actor = AuthenticatedActor("U-1", "C-1", frozenset())
    service = ProjectFinanceCommandService(bridge, recognition_source_provider=BadSources())
    obligation = approved_obligation(service, actor)
    with pytest.raises(PermissionError, match="obligation project"):
        service.create_recognition_proposal(actor, obligation_name=obligation["name"],
                                            period_end="2026-11-30", idempotency_key="rr-3")
