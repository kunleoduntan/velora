# Workflow, dashboards, printing and public website

## Workflow engine

Workflow definitions are stored in each company database. A definition identifies a DocType, initial state, states, optional document state field and transitions. A transition has an action, source state, target state, allowed roles and/or assigned users, conditional routing, approval policy and optional parallel approval branches. Parallel branches each have their own approvers and quorum and the transition advances only after all branches complete. Workflow events can emit custom notifications through `velora_notify`. Workflow actions require the document to be readable and the acting user to hold one of the transition roles. The approval role is the authorization for the state transition; it does not automatically grant general write access to every field on the document.

API: `GET/POST /api/workflows`, `POST /api/workflows/{name}/start`, `GET /api/workflow-instances/{id}`, `POST /api/workflow-instances/{id}/action`, `GET /api/workflow-inbox`, and `POST /api/workflows/{name}/simulate`. SLA escalations use company-local durable jobs and registered app handlers.

## Dashboards

Dashboard definitions and widgets are company-local. Supported widget types are `number`, `group_by` and `aggregate`. The existing DocType permission and safe query layers enforce access when widgets execute. Dashboard authoring is restricted to System Manager; private dashboards are owner-only and public dashboards are visible within the company.

API: `GET/POST /api/dashboards`, `GET /api/dashboards/{id}`, `GET /api/dashboards/{id}/run`, `DELETE /api/dashboards/{id}`.

## Print formats

Print formats are company-local. Templates use escaped placeholders such as `{{ customer_name }}`. HTML preview is available for browser printing. PDF generation requires `pip install velora[pdf]`. The initial PDF renderer is a text-oriented fallback; richer page layout, child-table rendering and a full drag-and-drop designer are follow-on work. The current Desk editor stores an HTML template with escaped field placeholders.

## Public website

Website pages are company-local and rendered by the React/TypeScript Desk bundle at `/site/<slug>`. In platform mode, public page resolution requires an active company domain mapping. Content blocks support text, images and links. Commerce-specific product catalogues, cart, checkout, payment, tax and fulfilment are application-level capabilities, not framework-core business logic. Customer/supplier portal authentication and private authenticated portal APIs are a follow-on phase; this batch provides public pages and the React extension point.

## Application website extensions

The React website renderer exposes `registerWebsiteBlock(type, Component)` from `frontend/src/website/blocks.tsx`. An installed app can register a custom block renderer. A commerce app can use this extension point for its product catalogue, cart and checkout components, while retaining ownership of inventory availability, pricing, tax, payments, order processing and fulfilment.

## Advanced workflow configuration (v0.14)

The guided Workflow Desk builder configures states and transitions without JSON editing. Transitions support single, any, all and quorum approval policies, multiple conditions with all/any logic, and named-user or role-based approvers. Definitions are immutable-versioned; each running instance retains its starting version. Company-local delegations, reusable templates, approved app-owned automation handler declarations and SLA deadline records are available through the v0.14 API. See `v0_14.md` for endpoints and current boundaries.
\n\n## Visual workflow designer and transition activities (v0.16)\n\nThe graphical designer stores node coordinates in the existing workflow state definition. Transitions can dispatch registered installed-app handlers for notification, task, timer, sub-process or custom activities. Delayed activities use the durable company-local job queue. Historical workflow versions can be restored as a new version; active instances remain pinned to the snapshot captured at start.\n