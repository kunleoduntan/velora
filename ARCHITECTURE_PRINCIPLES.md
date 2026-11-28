# Velora Architecture Principles — v0.70.0

## Product ambition

Velora is being engineered to compete with and ultimately exceed established enterprise application
frameworks, including Frappe and other widely used platforms. This is a product ambition and an
engineering standard, not a claim that every capability is already complete or benchmarked.

The framework must earn that position through measurable qualities: extensibility, configuration
depth, security, correctness, developer experience, operational reliability, performance,
interoperability, upgrade safety, and production support.

## Core design contract

1. **Configuration before custom code.** Organisational policy and routine business behaviour
   should be expressed through metadata and administrative configuration.
2. **One reusable engine.** Applications consume the framework's shared document, permission,
   workflow, rule, reporting, notification, automation, audit, naming, form, and dashboard engines.
   Applications must not ship competing copies of those engines.
3. **No hard-coded organisational policy.** Role assignments, record scopes, approval chains,
   thresholds, notification routing, and report layouts must be configurable per organisation.
4. **Trusted code remains legitimate.** Application-specific calculations, external integrations,
   specialised algorithms, and controlled extension handlers may require code. Untrusted
   configuration must never be executed as Python or JavaScript.
5. **Tenant isolation is mandatory.** Configuration, records, audit evidence, and runtime state
   must remain within the active tenant/company database boundary unless an explicitly designed
   cross-tenant control-plane feature is used.
6. **Version and audit configuration.** Changes to security policies, workflows, rules, and
   financial configuration need attributable history and safe publication/rollback semantics.
7. **Fail closed on security decisions.** An unavailable or invalid permission/rule policy must
   never silently widen access.
8. **API-first, UI-complete.** Every core capability should have a documented service contract and
   administrative UI. An API-only feature is not considered a finished end-user experience.
9. **Database portability.** Core data access must preserve supported dialect behaviour and avoid
   hidden dependence on one database vendor.
10. **Testable by contract.** Engines must have isolated unit tests, integration tests, security
    tests, tenant-isolation tests, and upgrade/migration tests.

## Core engine map

| Engine | Shared responsibility | Organisation-specific configuration |
|---|---|---|
| Metadata | DocTypes, fields, links, child tables, validation metadata | Schemas and field behaviour |
| Document | CRUD, lifecycle, submission, cancellation, concurrency | Document lifecycle policy |
| Permission | Roles, actions, field access, record-level scope, sharing | Who can do what and to which records |
| Workflow | States, transitions, approvals, delegation, escalation | Approval routes and thresholds |
| Rule | Safe condition evaluation and reusable named policies | Conditions and rule parameters |
| Reporting | Query/report definitions, filters, grouping, formulas, exports | Report layouts and access |
| Notification | Templates, channels, recipients, delivery and retry | Message content and routing |
| Automation | Event and schedule orchestration | Trigger and permitted action configuration |
| Audit | Evidence of changes, decisions and access-sensitive events | Retention and review policy |
| Organisation | Configurable organisational hierarchy and dimensions | Structure, units and relationships |
| Form/UI | Form layouts, conditional visibility, actions and list configuration | User experience and form design |
| Dashboard | KPIs, charts, cards and drill-downs | Role/workspace dashboards |

## Rule Engine in v0.70.0

The first reusable Rule Engine release provides:
- A JSON condition DSL with nested `all`, `any`, and `not` groups.
- Comparisons, membership, string matching, and set/unset checks.
- Document field references and controlled execution-context references (`$user`, etc.).
- A bounded evaluator with depth and node limits.
- Named, company-local rule definitions with scope, enabled state, and version increments.
- Administrative CRUD and a rule-test API.
- No arbitrary source execution.

Rule Studio:
- A graphical Rule Studio is now available from the Tools navigation.
- Administrators can create, edit, test, and delete reusable rules.
- Workflow transition designer can reference a named rule by name.
- Workflow simulation, approval inbox eligibility, and actual transition execution evaluate the
  linked rule against the document and controlled execution context. A false rule blocks the
  transition, including parallel approval transitions.

Rule API:
- `GET /api/rules`
- `GET /api/rule/{name}`
- `POST /api/rules`
- `PUT /api/rule/{name}`
- `DELETE /api/rule/{name}`
- `POST /api/rule/{name}/test`

Only Administrator/System Manager may manage rule definitions in this release. Rule evaluation is safe and reusable, but full graphical Rule Studio, approval/publishing lifecycle, dependency mapping, and integration into every permission/workflow/automation decision remain roadmap work. Existing engines retain their existing policy formats until those integrations are migrated and covered by security regression tests.

## Competitive engineering programme

To credibly supersede established frameworks, Velora must progressively demonstrate:
- A complete low-code/no-code configuration experience for common enterprise processes.
- Rich workflow patterns, policy simulation, version publication, delegation, SLA and audit.
- Fine-grained security with field, record, action, hierarchy and context-aware access.
- A mature developer SDK, extension points, test harness, package ecosystem and documentation.
- Production-grade tenancy, backups, restore drills, observability, high availability and disaster recovery.
- Database portability and reproducible performance benchmarks.
- Accessible, responsive, consistent administration and end-user interfaces.
- Upgrade compatibility, migration previews, rollback plans and long-term support discipline.

No framework should be declared superior solely by feature count. Each release should close a specific gap and include tests and evidence.
