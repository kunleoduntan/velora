"""Conformance tests for the injected Velora host integration ports."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from velora_projectone.projectone.integrations.host_adapter import (
    VeloraProjectRepository, authenticated_actor_from_host,
)
from velora_projectone.projectone.integrations.host_contracts import (
    AuthenticatedActor, HostCapabilities,
)
from velora_projectone.projectone.services.persistence import VersionConflict


ALL_CAPABILITIES = HostCapabilities(True, True, True, True, True, True)


class FakeBridge:
    def __init__(self, capabilities=ALL_CAPABILITIES):
        self.rows, self.events, self.keys = {}, [], {}
        self.fail_audit = False
        self.uow = self
        self.projects = self
        self.audit = self
        self.idempotency = self
        self._capabilities = capabilities

    def capabilities(self):
        return self._capabilities

    @contextmanager
    def transaction(self):
        snapshot = deepcopy((self.rows, self.events, self.keys))
        try:
            yield self
        except Exception:
            self.rows, self.events, self.keys = snapshot
            raise

    def get(self, session, project_id, company_id):
        row = self.rows.get(project_id)
        return deepcopy(row) if row and row["company"] == company_id else None

    def list(self, session, company_id, *, status, limit, offset):
        rows = [deepcopy(r) for r in self.rows.values()
                if r["company"] == company_id and (status is None or r.get("status") == status)]
        return sorted(rows, key=lambda r: r["project_code"])[offset:offset + limit]

    def insert(self, session, document, *, actor_id):
        row = deepcopy(document)
        row.update(name=row.get("name", "P-" + str(len(self.rows) + 1)), version=1, company="C1")
        self.rows[row["name"]] = row
        return deepcopy(row)

    def update_if_version(self, session, project_id, company_id, document, *, expected_version, actor_id):
        current = self.get(session, project_id, company_id)
        if not current or current["version"] != expected_version:
            raise VersionConflict("stale")
        row = deepcopy(document)
        row.update(name=project_id, company=company_id, version=expected_version + 1)
        self.rows[project_id] = row
        return deepcopy(row)

    def append(self, session, *, company_id, project_id, actor_id, action, before, after):
        if self.fail_audit:
            raise RuntimeError("audit unavailable")
        self.events.append({"company": company_id, "project_id": project_id,
                            "actor": actor_id, "action": action,
                            "before": deepcopy(before), "after": deepcopy(after)})

    def list_for_project(self, session, project_id, company_id, *, limit):
        return [deepcopy(e) for e in self.events
                if e["project_id"] == project_id and e["company"] == company_id][-limit:]

    def execute(self, session, company_id, key, request_hash, operation):
        compound = (company_id, key)
        if compound in self.keys:
            old_hash, response = self.keys[compound]
            if old_hash != request_hash:
                raise ValueError("idempotency conflict")
            return deepcopy(response)
        response = operation(session)
        self.keys[compound] = (request_hash, deepcopy(response))
        return response


def test_host_adapter_requires_all_production_capabilities():
    partial = HostCapabilities(True, True, False, True, True, True)
    with pytest.raises(RuntimeError, match="compare_and_swap_updates"):
        VeloraProjectRepository(FakeBridge(partial))
    assert VeloraProjectRepository(FakeBridge(partial), require_production_capabilities=False)


def test_host_adapter_create_is_transactional_and_audited():
    bridge = FakeBridge()
    repo = VeloraProjectRepository(bridge)
    saved = repo.insert({"project_code": "P1", "title": "ERP"}, actor_id="U1", scope="C1")
    assert saved["version"] == 1
    assert len(repo.audit_events(saved["name"], "C1")) == 1


def test_host_adapter_rolls_back_document_when_audit_fails():
    bridge = FakeBridge()
    bridge.fail_audit = True
    repo = VeloraProjectRepository(bridge)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        repo.insert({"project_code": "P1"}, actor_id="U1", scope="C1")
    assert bridge.rows == {} and bridge.events == []


def test_host_adapter_tenant_scope_and_pagination():
    repo = VeloraProjectRepository(FakeBridge())
    row = repo.insert({"project_code": "P1"}, actor_id="U1", scope="C1")
    assert repo.get(row["name"], "C2") is None
    assert repo.list("C2") == []
    with pytest.raises(ValueError):
        repo.list("C1", limit=501)


def test_host_adapter_compare_and_swap_rejects_stale_write():
    repo = VeloraProjectRepository(FakeBridge())
    row = repo.insert({"project_code": "P1"}, actor_id="U1", scope="C1")
    updated = dict(row, title="Revised")
    saved = repo.update(row["name"], "C1", updated, expected_version=1, actor_id="U2")
    assert saved["version"] == 2
    with pytest.raises(VersionConflict):
        repo.update(row["name"], "C1", updated, expected_version=1, actor_id="U3")


def test_host_adapter_audit_failure_rolls_back_update():
    bridge = FakeBridge()
    repo = VeloraProjectRepository(bridge)
    row = repo.insert({"project_code": "P1"}, actor_id="U1", scope="C1")
    bridge.fail_audit = True
    with pytest.raises(RuntimeError):
        repo.update(row["name"], "C1", dict(row, title="X"), expected_version=1, actor_id="U2")
    assert repo.get(row["name"], "C1")["version"] == 1


def test_host_adapter_idempotency_delegates_atomic_replay():
    repo = VeloraProjectRepository(FakeBridge())
    calls = []
    operation = lambda session: calls.append("run") or {"ok": True}
    assert repo.execute_idempotent("C1", "K1", "HASH", operation) == {"ok": True}
    assert repo.execute_idempotent("C1", "K1", "HASH", operation) == {"ok": True}
    assert calls == ["run"]


def test_authenticated_actor_must_be_host_authenticated():
    with pytest.raises(PermissionError):
        authenticated_actor_from_host(SimpleNamespace(is_authenticated=False))
    principal = SimpleNamespace(is_authenticated=True, user_id="U1", company_id="C1",
                                roles=["Project Manager"], permissions=["project.read"])
    actor = authenticated_actor_from_host(principal)
    assert actor == AuthenticatedActor("U1", "C1", frozenset({"Project Manager"}),
                                       frozenset({"project.read"}))


def test_authenticated_actor_rejects_string_roles():
    principal = SimpleNamespace(is_authenticated=True, user_id="U1", company_id="C1",
                                roles="Project Manager", permissions=[])
    with pytest.raises(TypeError):
        authenticated_actor_from_host(principal)


def test_existing_project_command_service_runs_against_host_repository():
    from velora_projectone.projectone.services.persistence import ProjectCommandService
    repo = VeloraProjectRepository(FakeBridge())
    commands = ProjectCommandService(repo)
    created = commands.create("C1", "U1", {
        "project_code": "HOST-001", "title": "Host-backed project",
        "project_manager": "PM-1", "start_date": "2026-01-01", "end_date": "2026-03-31",
    })
    proposed = commands.transition("C1", "U1", created["name"], "Proposed", {}, 1)["project"]
    assert proposed["status"] == "Proposed" and proposed["version"] == 2
    with pytest.raises(ValueError):
        commands.update("C1", "U1", created["name"], {"status": "Active"}, 2)


def test_projectone_frontend_assets_are_declared_and_packaged():
    from pathlib import Path
    import velora_projectone
    import velora_projectone.hooks as hooks

    root = Path(velora_projectone.__file__).resolve().parent
    assert hooks.frontend_assets == ["frontend/projectone-forms.js", "frontend/projectone-agile.js", "frontend/projectone-resources.js", "frontend/projectone-finance.js", "frontend/projectone-dashboards.js", "frontend/projectone-executive.js", "frontend/projectone-schedule.js", "frontend/projectone-workbench.js", "frontend/projectone-capacity.js", "frontend/projectone-programme-intelligence.js", "frontend/projectone.css"]
    for asset in hooks.frontend_assets:
        target = root / asset
        assert target.is_file() and target.stat().st_size > 100


def test_projectone_custom_forms_only_reference_real_doctype_fields():
    import json
    import re
    from pathlib import Path
    import velora_projectone

    root = Path(velora_projectone.__file__).resolve().parent
    js = (root / "frontend/projectone-forms.js").read_text()
    definitions = {
        "Project": "project",
        "Project Portfolio": "project_portfolio",
        "Project Programme": "project_programme",
    }
    component_names = {
        "Project": "ProjectForm",
        "Project Portfolio": "PortfolioForm",
        "Project Programme": "ProgrammeForm",
    }
    for doctype, folder in definitions.items():
        metadata = json.loads((root / "projectone" / "doctype" / folder / f"{folder}.json").read_text())
        allowed = {field["fieldname"] for field in metadata["fields"]}
        start = js.index(f"function {component_names[doctype]}")
        end = js.find("\n  function ", start + 10)
        if end < 0:
            end = js.find("window.Velora.register", start)
        used = set(re.findall(r'field\("[^"]+","([a-z0-9_]+)"', js[start:end]))
        assert used <= allowed, f"{doctype} form references undefined fields: {sorted(used - allowed)}"
        assert f'window.Velora.registerFormComponent("{doctype}"' in js
