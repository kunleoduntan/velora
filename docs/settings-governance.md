# Velora Settings Governance — v0.22.0

The framework provides a reusable governance engine. Domain applications register their own setting contracts; this is not a replacement for typed Finance Settings, Inventory Settings or future Sales, Tax, Purchasing and Payroll settings DocTypes.

## Operating model

1. Register a catalogue definition with a unique key, domain, value type, permitted scopes, risk class and optional default.
2. A System Manager creates a change request with a business reason and effective date.
3. The maker submits the request.
4. A different System Manager approves it. Critical settings require two distinct approvers.
5. An approver publishes the approved request. Publishing appends an immutable version.
6. Business services resolve the effective setting for a scope and date.
7. To promote settings to another environment/entity, export a checksum-protected package. Import verifies the checksum and stages Draft requests for each effective-date boundary; it never publishes automatically.

All records are stored in the active company database. Legal-entity settings therefore remain isolated under the database-per-legal-entity model.

## Catalogue definition example

```json
{
  "name": "sales.default_warehouse",
  "title": "Default Sales Warehouse",
  "description": "Default warehouse used by sales fulfilment when no explicit warehouse is supplied.",
  "domain": "sales",
  "value_type": "string",
  "allowed_scopes": ["legal_entity", "branch"],
  "fallback_scopes": ["legal_entity"],
  "default_value": null,
  "required": false,
  "risk": "normal"
}
```

Supported value types: `string`, `integer`, `decimal`, `boolean`, `date`, `json`, `secret_ref`.

Supported scopes: `legal_entity`, `branch`, `module`, `role`, `user`. A setting may only be used at scopes declared in its catalogue definition. Fallback is explicit; v0.22 supports legal-entity fallback only. Financial identity settings such as base currency and fiscal calendar should be legal-entity-only.

Risk levels: `normal`, `elevated`, `high`, `critical`. High and critical changes cannot be backdated. All changes use maker-checker; critical settings require two independent approvers.

## API

All endpoints require an authenticated System Manager or Administrator:

- `GET /api/settings/catalogue?domain=finance`
- `POST /api/settings/catalogue`
- `POST /api/settings/changes`
- `GET /api/settings/changes?status=pending_approval`
- `POST /api/settings/changes/{change_id}/submit`
- `POST /api/settings/changes/{change_id}/approve`
- `POST /api/settings/changes/{change_id}/publish`
- `POST /api/settings/changes/{change_id}/reject`
- `GET /api/settings/{setting_key}/effective?scope_type=legal_entity&on_date=2026-12-01`
- `GET /api/settings/{setting_key}/versions`
- `GET /api/settings/{setting_key}/audit`
- `GET /api/settings/package/export?setting=sales.default_warehouse`
- `POST /api/settings/package/import`

A business service can call `velora.settings_governance.get_effective(key, scope_type, scope_key, on_date)` directly. API access is restricted; internal services should call the service function rather than exposing configuration to ordinary users.

## Security and operational constraints

- Do not put credentials in setting values. Use a secret manager reference such as `secret://payments/provider-key`; v0.22 validates the reference format but does not itself provision or resolve the referenced secret.
- Do not store Python, SQL, JavaScript or arbitrary expressions in settings.
- Never edit or delete published version history. Correct a setting through a new change request.
- Package checksums detect accidental/tampered content; they are not a digital signature and do not prove the identity of the exporting environment.
- Importing a package creates Draft changes. It does not bypass local validation, approvals or publishing.
- Existing Finance Settings and Inventory Settings are preserved. Their migration into the catalogue requires explicit domain mapping and reconciliation and is not automatic in this release.
