"""Explicit project action policy. Host must construct principal from authenticated identity."""
from .policy import assert_project_access

ACTION_ROLES={
    "view": {"Project Sponsor","Project Manager","Project Coordinator","Project Member","Project Finance","Project Auditor"},
    "edit_plan": {"Project Manager","Project Coordinator"},
    "approve_baseline": {"Project Sponsor","Portfolio Manager"},
    "approve_budget": {"Project Sponsor","Portfolio Manager","Project Finance"},
    "approve_timesheet": {"Project Manager","Timesheet Approver"},
    "view_financials": {"Project Manager","Project Finance","Portfolio Manager","Project Sponsor","Project Auditor"},
    "close_project": {"Project Sponsor","Portfolio Manager"},
}

def authorize_project_action(principal, action, project_id, company):
    if action not in ACTION_ROLES: raise PermissionError("Unknown or unsupported project action.")
    assert_project_access(principal,project_id,company,ACTION_ROLES[action])
    return True
