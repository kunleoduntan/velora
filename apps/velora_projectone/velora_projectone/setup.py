"""ProjectOne lifecycle: the Projects workspace is created on install and kept current on upgrade."""
from __future__ import annotations

SHORTCUTS = (
    ("Projects", "Every project with status, health and budget", "#/app/Project"),
    ("Tasks", "Project tasks and dependencies", "#/app/Project Task"),
    ("Milestones", "Delivery milestones", "#/app/Project Milestone"),
    ("Risks", "Risk register", "#/app/Project Risk"),
    ("Issues", "Issue log", "#/app/Project Issue"),
    ("Change Requests", "Scope, cost and schedule change control", "#/app/Project Change Request"),
    ("Budgets", "Approved project budgets", "#/app/Project Budget"),
    ("Timesheets", "Time booked against projects", "#/app/Project Timesheet"),
    ("Portfolios", "Portfolio governance", "#/app/Project Portfolio"),
    ("Programmes", "Programme delivery", "#/app/Project Programme"),
)


def ensure_projects_workspace():
    from velora.application_workspaces import listing, save
    current = next((row for row in listing() if row.get("scope") == "company" and row.get("name") == "Projects"), None)
    widgets = list((current or {}).get("layout") or [])
    titles = {widget.get("title") for widget in widgets}
    widgets.extend({"type": "shortcut", "title": t, "description": d, "route": r, "width": 2}
                   for t, d, r in SHORTCUTS if t not in titles)
    save({"id": (current or {}).get("id"), "name": "Projects",
          "description": "Projects, programmes and portfolios with budgets, risks and delivery control.",
          "visibility": "company", "roles": [], "widgets": widgets}, "company")


def after_install():
    ensure_projects_workspace()


def after_migrate():
    ensure_projects_workspace()
