"""Test helpers for the GUI-managed approval workflows (v2.84)."""
from velora import workflows
from velora.permissions import Session, session_as

ADMIN = Session("Administrator", frozenset({"System Manager"}))


def install_approval(doctype, roles=("Finance Manager",), **extra):
    """Give the company a starter approval workflow for one document type (what a System Manager does in Settings > Workflows)."""
    from velora_erp.finance.workflow_templates import _definition
    with session_as(ADMIN):
        return workflows.save_definition({**_definition(doctype, list(roles)), "enabled": True, **extra})


def decide(doctype, name, action, who, comment=""):
    """Take a workflow action on a document, as `who`."""
    inst = workflows.document_workflow(doctype, name)["instance_id"]
    with session_as(who):
        return workflows.act(inst, action, comment)
