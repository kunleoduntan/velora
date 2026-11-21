from types import SimpleNamespace
import pytest
from velora.tenant_security import resolve_tenant_company, assert_same_tenant
from velora.exceptions import CompanyAccessDenied, CompanyUnavailable

class Identity:
    def __init__(self, company, roles=("Accounts User",)):
        self.company, self.roles = company, roles
    def authorize(self, auth, company_id):
        if not self.company or company_id != self.company["id"]:
            raise CompanyAccessDenied("You do not have access to this company")
        return self.company, list(self.roles)
class Registry:
    def __init__(self, tenant): self.tenant = tenant
    def get_tenant(self, tenant_id):
        return self.tenant if self.tenant and self.tenant["id"] == tenant_id else None

def plane(company, tenant, roles=("Accounts User",)):
    return SimpleNamespace(identity=Identity(company, roles), registry=Registry(tenant))

def test_resolves_authorized_tenant_company_and_roles():
    p=plane({"id":"COMP-001","name":"Acme","tenant_id":"TEN-001","status":"active"},
            {"id":"TEN-001","name":"Acme Group","status":"active"})
    c=resolve_tenant_company(p, object(), "COMP-001")
    assert (c.tenant_id,c.company_id,c.roles)==("TEN-001","COMP-001",("Accounts User",))

def test_tenant_pin_blocks_cross_tenant_company():
    p=plane({"id":"COMP-001","name":"Acme","tenant_id":"TEN-001","status":"active"},
            {"id":"TEN-001","name":"Acme Group","status":"active"})
    with pytest.raises(CompanyAccessDenied): resolve_tenant_company(p, object(), "COMP-001", "TEN-002")

def test_suspended_tenant_and_company_fail_closed():
    co={"id":"COMP-001","name":"Acme","tenant_id":"TEN-001","status":"active"}
    with pytest.raises(CompanyUnavailable):
        resolve_tenant_company(plane(co,{"id":"TEN-001","name":"Acme Group","status":"suspended"}),object(),"COMP-001")
    co["status"]="suspended"
    with pytest.raises(CompanyUnavailable):
        resolve_tenant_company(plane(co,{"id":"TEN-001","name":"Acme Group","status":"active"}),object(),"COMP-001")

def test_resource_tenant_boundary():
    p=plane({"id":"COMP-001","name":"Acme","tenant_id":"TEN-001","status":"active"},
            {"id":"TEN-001","name":"Acme Group","status":"active"})
    ctx=resolve_tenant_company(p,object(),"COMP-001")
    assert_same_tenant(ctx,"TEN-001")
    with pytest.raises(CompanyAccessDenied): assert_same_tenant(ctx,"TEN-002")
