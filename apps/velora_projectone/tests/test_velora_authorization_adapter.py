import pytest

from velora_projectone.projectone.integrations.velora_authorization import (
    VeloraFrappeAuthorizationAdapter,
)


def test_permission_slug_maps_to_native_doctype_action():
    adapter = VeloraFrappeAuthorizationAdapter()
    assert adapter._resolve_permission("projectone.project.create") == ("Project", "create")
    assert adapter._resolve_permission("projectone.task.update") == ("Project Task", "write")
    assert adapter._resolve_permission("projectone.project.audit.read") == ("Project", "read")
    assert adapter._resolve_permission("project_performance_obligation.approve") == (
        "Project Performance Obligation", "approve"
    )


def test_custom_inbox_permission_requires_host_checker():
    adapter = VeloraFrappeAuthorizationAdapter()
    assert adapter._resolve_permission("projectone.workflow.inbox.read") == (
        None, "workflow.inbox.read"
    )


def test_unknown_permission_is_rejected():
    adapter = VeloraFrappeAuthorizationAdapter()
    with pytest.raises(PermissionError):
        adapter._resolve_permission("projectone.unknown.read")


def test_unknown_doctype_mapping_is_rejected():
    with pytest.raises(ValueError):
        VeloraFrappeAuthorizationAdapter(doctype_map={"Unknown": "Unknown"})
