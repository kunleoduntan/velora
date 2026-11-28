from copy import deepcopy
import pytest
from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
from velora_projectone.projectone.integrations.source_readers import (
    ProjectOneReadIntegration, IntegrationAccessError, IntegrationDataError,
    ReadQuery,
)

class Adapter:
    source_name = "accounting"
    def __init__(self, rows): self.rows, self.queries = rows, []
    def read(self, query):
        self.queries.append(query)
        return deepcopy(self.rows)

class Registry:
    def __init__(self, adapters): self.adapters = adapters
    def get(self, name): return self.adapters.get(name)

def actor(perms=frozenset({"projectone.integration.accounting.read"})):
    return AuthenticatedActor("U1", "C1", frozenset({"Project Manager"}), perms)

def test_read_integration_enforces_trusted_actor_and_permission():
    svc = ProjectOneReadIntegration(Registry({"accounting": Adapter([])}))
    with pytest.raises(IntegrationAccessError): svc.collect({"company_id": "C1"}, {"accounting": ["cost_actuals"]})
    with pytest.raises(IntegrationAccessError): svc.collect(actor(frozenset()), {"accounting": ["cost_actuals"]})

def test_source_query_is_company_and_project_scoped_and_read_only():
    adapter = Adapter([{"company": "C1", "project_id": "P1", "amount": 10}])
    result = ProjectOneReadIntegration(Registry({"accounting": adapter})).collect(
        actor(), {"accounting": ["cost_actuals"]}, project_id="P1")
    assert adapter.queries[0].company_id == "C1"
    assert adapter.queries[0].project_id == "P1"
    assert result["data"]["cost_actuals"][0]["amount"] == 10
    assert result["metadata"]["read_only"] is True
    assert result["provenance"]["accounting"]["read_only"] is True

def test_cross_project_source_response_is_rejected():
    svc = ProjectOneReadIntegration(Registry({"accounting": Adapter([{"company": "C1", "project_id": "P2"}])}))
    with pytest.raises(IntegrationDataError, match="Cross-project"):
        svc.collect(actor(), {"accounting": ["cost_actuals"]}, project_id="P1")

def test_source_collection_allowlist_and_missing_adapter_reporting():
    svc = ProjectOneReadIntegration(Registry({}))
    with pytest.raises(ValueError, match="not supplied"):
        svc.collect(actor(), {"accounting": ["employee_passwords"]})
    result = svc.collect(actor(), {"accounting": ["cost_actuals"]})
    assert result["provenance"]["accounting"]["status"] == "not_configured"
    readiness = svc.readiness()
    assert readiness["configured_count"] == 0 and not readiness["production_ready"]

def test_read_query_rejects_unbounded_limits():
    with pytest.raises(ValueError): ReadQuery("C1", "cost_actuals", limit=5001)
