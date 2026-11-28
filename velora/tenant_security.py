"""Tenant-aware authorization boundary for Velora platform requests.

The control plane owns identity and routing metadata. Business data remains in the
company database selected only after this boundary has authorized the user.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from .exceptions import CompanyAccessDenied, CompanyUnavailable


@dataclass(frozen=True)
class TenantCompanyContext:
    tenant_id: str
    tenant_name: str
    company_id: str
    company_name: str
    roles: tuple[str, ...]


def resolve_tenant_company(plane: Any, auth: Any, company_id: str | None,
                           expected_tenant_id: str | None = None) -> TenantCompanyContext:
    """Authorize membership, tenant lifecycle and optional tenant pinning.

    Never accept tenant identity from an untrusted request as authorization.
    `expected_tenant_id` is an additional constraint (e.g. a tenant-scoped API
    credential); membership is always re-checked against the control plane.
    """
    company, roles = plane.identity.authorize(auth, company_id)
    tenant_id = str(company.get("tenant_id") or "")
    if expected_tenant_id and tenant_id != expected_tenant_id:
        # Do not disclose whether the target company or tenant exists.
        raise CompanyAccessDenied("You do not have access to this company")
    tenant = plane.registry.get_tenant(tenant_id)
    if not tenant or tenant.get("status") != "active":
        raise CompanyUnavailable("This tenant is suspended")
    if company.get("status") != "active":
        raise CompanyUnavailable(f"This company is {company.get('status', 'unavailable')}")
    return TenantCompanyContext(
        tenant_id=tenant_id,
        tenant_name=str(tenant.get("name") or ""),
        company_id=str(company["id"]),
        company_name=str(company.get("name") or ""),
        roles=tuple(roles),
    )


def assert_same_tenant(context: TenantCompanyContext, resource_tenant_id: str) -> None:
    """Fail closed when a resource belongs to a different tenant."""
    if not resource_tenant_id or context.tenant_id != resource_tenant_id:
        raise CompanyAccessDenied("Cross-tenant access is not permitted")
