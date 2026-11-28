# Security and Accounting Controls

1. Never bypass Velora's authenticated API route wrapper.
2. Build the actor only from the authenticated Velora session (user and roles). Never accept these values from client request bodies.
3. Apply project row scopes before reads, writes, list queries, exports, reports, search and background jobs. Service-level role checks are not a substitute for database/query-level row filtering.
4. Use `authorize_project_action` as a policy primitive and map roles to the site's actual role catalogue before enabling actions. Unknown actions fail closed.
5. Apply financial-field redaction server-side and independently enforce financial permissions at the query layer.
6. AI context must be permission-filtered and read-only. ProjectOne insight service is advisory and must not invoke tools, mutate records or approve changes.
7. Approved budgets and baselines are versioned; no silent overwrite. Use optimistic concurrency and durable audit events in the host repository.
8. Commitments are not actual costs; reconcile source PO/contract values against invoiced/received/released amounts.
9. Accounting postings originate only in authorised source applications and the shared Accounting service. ProjectOne must never create General Ledger entries.
10. Project closure is blocked while mandatory financial, deliverable, commitment or handover checks remain incomplete.
11. Approved timesheets are a hand-off to Payroll/Accounting; ProjectOne does not calculate payroll or post salary journals.
12. Run tenant isolation, role escalation, concurrency and audit integrity tests in staging before production.

## Host integration requirement

The package provides policy primitives and a route provider. The host application must bind them to its authenticated principal, durable repository, workflow engine, audit service and row-level query filters. Do not deploy the in-memory repository adapter.
