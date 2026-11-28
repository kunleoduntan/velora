# Velora ProjectOne Architecture

## Product boundary

ProjectOne owns project and portfolio records: Project, Portfolio, Programme, Task, WBS, Milestone, Baseline, Risk, Issue, Change Request, Deliverable, Budget, Timesheet, Resource, Sprint and the governance documents (charter, business case, stage gate, closure). It is not a ledger. VeloraERP owns purchasing, payroll, inventory, assets and accounting; ProjectOne reads their figures per project.

## One database, no company field

Velora keeps one database per site, so no ProjectOne doctype has a company field. The services take a fixed scope label supplied by the host (`site`) only to satisfy their ports; it is never stored on a record.

## How it is wired

`api_routes.install_routes` wraps the framework's request runner with `velora_host.install`. For every request it builds the actor from the signed-in Velora session, then ProjectOne's services call these ports, all implemented in `velora_host.py`:

| Port | Velora implementation |
|---|---|
| document engine | `get_doc`, `get_list`, `new_doc`, `save` under the user's session; optimistic version = modified timestamp |
| transactions | `db.transaction()` (nested calls join the request's transaction) |
| authorization | DocPerm rows via `has_permission`, field level via `field_access` |
| audit | append-only `Project Audit Event` documents |
| repeat-request protection | `Project Request Key` documents |
| workflow | the shared Workflow Designer (`workflows.start`, `workflows.act`, approval inbox) |
| source data | read-only ERP ledger (cost, revenue, project positions) and ProjectOne allocations |

Plain Python errors from the services are returned as proper HTTP answers (403, 404, 422).

## Lifecycle and approvals

Approval is never coded: states and approvers come from the Workflow Designer, configured per site. Controllers validate dates, progress and budget; protected fields (status, approval fields) change only through the governed endpoints.

## Scheduling and resources

An integer-unit CPM engine validates the dependency graph and calculates early/late dates and float for FS, SS, FF and SF links. A calendar-aware planner uses working weekdays and holidays. Resource levelling and capacity are read models over allocations and calendars.

## AI

Project insight generation is deterministic and advisory only; it never changes or approves a record.
