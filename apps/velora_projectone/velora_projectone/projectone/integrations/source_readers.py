"""Read-only, tenant-scoped integration contracts for Velora source systems.

ProjectOne consumes authoritative records; it never writes back to Accounting,
HRMS, Procurement, Sales, Inventory or Fixed Assets through these interfaces.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, Any


SOURCE_COLLECTIONS = {
    "accounting": frozenset({"project_positions", "cost_actuals", "recognised_revenue", "receivables", "payments"}),
    "hrms": frozenset({"resources", "allocations", "timesheets", "labour_costs"}),
    "procurement": frozenset({"contracts", "purchase_orders", "commitments", "supplier_performance"}),
    "sales": frozenset({"customer_contracts", "billing_milestones", "claims", "variations"}),
    "inventory": frozenset({"material_usage", "stock_commitments"}),
    "fixed_assets": frozenset({"asset_allocations", "depreciation_readings"}),
}


@dataclass(frozen=True)
class ReadQuery:
    company_id: str
    collection: str
    project_id: str | None = None
    modified_since: str | None = None
    limit: int = 500

    def __post_init__(self):
        if not self.company_id:
            raise ValueError("Company scope is required.")
        if not 1 <= self.limit <= 5000:
            raise ValueError("Read limit must be between 1 and 5000.")


class SourceReadPort(Protocol):
    """Implementations must enforce company_id in the source query itself."""
    source_name: str
    def read(self, query: ReadQuery) -> list[dict[str, Any]]: ...


class SourceRegistryPort(Protocol):
    def get(self, source_name: str) -> SourceReadPort | None: ...


class IntegrationAccessError(PermissionError):
    pass


class IntegrationDataError(ValueError):
    pass


class ProjectOneReadIntegration:
    """Permission-gated fan-in for authoritative source-system read models."""
    def __init__(self, registry: SourceRegistryPort, *, max_records_per_source: int = 1000):
        if not 1 <= max_records_per_source <= 5000:
            raise ValueError("max_records_per_source must be between 1 and 5000.")
        self.registry = registry
        self.max_records_per_source = max_records_per_source

    def collect(self, actor, requests: dict[str, list[str]], *, project_id: str | None = None,
                modified_since: str | None = None) -> dict:
        # Actor must be the trusted immutable host principal, never a request body.
        from .host_contracts import AuthenticatedActor
        if not isinstance(actor, AuthenticatedActor):
            raise IntegrationAccessError("Trusted authenticated host actor is required.")
        if not isinstance(requests, dict) or not requests:
            raise ValueError("At least one source collection is required.")
        result, provenance = {}, {}
        for source_name, collections in requests.items():
            if source_name not in SOURCE_COLLECTIONS:
                raise ValueError(f"Unsupported integration source: {source_name}.")
            permission = f"projectone.integration.{source_name}.read"
            if permission not in actor.permissions and "projectone.integration.read_all" not in actor.permissions:
                raise IntegrationAccessError(f"Missing permission: {permission}.")
            if not isinstance(collections, list) or not collections:
                raise ValueError(f"{source_name} collections must be a non-empty list.")
            for collection in collections:
                if collection not in SOURCE_COLLECTIONS[source_name]:
                    raise ValueError(f"{collection} is not supplied by {source_name}.")
            source = self.registry.get(source_name)
            if source is None:
                provenance[source_name] = {"status": "not_configured", "collections": []}
                continue
            source_rows = {}
            for collection in collections:
                query = ReadQuery(actor.company_id, collection, project_id,
                                  modified_since, self.max_records_per_source)
                rows = source.read(query)
                if not isinstance(rows, list):
                    raise IntegrationDataError(f"{source_name}.{collection} must return a list.")
                checked = []
                for row in rows:
                    if not isinstance(row, dict):
                        raise IntegrationDataError("Source records must be objects.")
                    # Defense in depth: source query MUST scope; response is checked too.
                    if project_id and str(row.get("project_id")) != str(project_id):
                        raise IntegrationDataError(f"Cross-project row returned by {source_name}.{collection}.")
                    checked.append(dict(row))
                source_rows[collection] = checked
            result.update(source_rows)
            provenance[source_name] = {"status": "connected", "collections": list(source_rows),
                                        "records": sum(map(len, source_rows.values())),
                                        "read_only": True}
        return {"company_scope": actor.company_id, "project_scope": project_id,
                "data": result, "provenance": provenance,
                "metadata": {"read_only": True, "source_of_truth": "upstream_systems",
                             "collected_at": datetime.now(timezone.utc).isoformat()}}

    def readiness(self) -> dict:
        sources = {}
        for name, collections in SOURCE_COLLECTIONS.items():
            adapter = self.registry.get(name)
            sources[name] = {"configured": adapter is not None,
                             "supported_collections": sorted(collections),
                             "write_access": False}
        return {"sources": sources,
                "configured_count": sum(1 for x in sources.values() if x["configured"]),
                "total_sources": len(sources),
                "production_ready": all(x["configured"] for x in sources.values()),
                "qualification": "adapter presence only; live credentials, tenant isolation and source reconciliation require deployment tests"}
