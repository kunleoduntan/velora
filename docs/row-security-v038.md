# Velora v0.38 — Row-Level Security

Velora v0.38 adds company-database-local row policies to the generic document engine.

## Policy model

A policy is keyed by `(role, doctype, permission)`. Conditions within one policy are ANDed. Policies inherited or assigned through multiple active roles are ORed. A configured policy therefore narrows the rows available to the user; no configured policy preserves the existing DocType permission behavior.

Supported operators:

- `equals_user`: field must equal the authenticated session user (normally used with `owner`).
- `eq`, `ne`: compare with a literal value.
- `in`, `not_in`: compare with a bounded list of literal values.
- `is_set`, `is_not_set`: test for a non-empty or empty field.
- `in_user_roles`: field value must match one of the user's expanded Velora roles.

Conditions are structured JSON. Raw SQL, Python expressions, joins, and arbitrary functions are not accepted. Fields are validated against DocType metadata at policy creation and again when a query is compiled.

## Administration example

```python
from velora.controlplane.role_admin import RoleAdministration

roles = RoleAdministration(company_engine)
roles.set_row_policy(
    actor=company_admin,
    role="Sales User",
    doctype="Customer",
    permission="read",
    conditions=[{"field": "owner", "operator": "equals_user"}],
)
```

The same pattern can be used for `create`, `write`, `delete`, `submit`, `cancel`, `export`, `print`, and `share`. Create policies are checked after the framework stamps the document owner. Write policies are checked against both the existing and resulting record, preventing a user from changing an ownership/scope field to escape the policy.

## Enforcement coverage

The generic document engine applies row policies to `get_doc`, `get_list`, `get_count`, `get_group_by`, and `get_aggregate`. Mutations are checked for create, write, delete, submit, and cancel. The generic query builder compiles policies to bound SQLAlchemy predicates; no result-set post-filtering is used.

## Semantics and safeguards

- Policies are stored in `velora_row_policy` inside each company database, not in the central control plane.
- Conditions in one policy are combined with AND; policies across a user's roles are combined with OR.
- A role with a configured policy is restricted to matching records for that operation.
- A role with no policy for an operation retains existing DocType permission semantics.
- Administrator and explicit trusted `ignore_permissions=True` paths retain their existing framework bypass semantics. Do not expose these trusted paths to ordinary users.
- The feature does not yet automatically rewrite arbitrary custom SQL, third-party report SQL, or external database access. Such code must use the safe document/query APIs or explicitly apply equivalent authorization.
- User identity and role context must be established by the authentication layer. `Session.attributes` is reserved for future trusted context expansion; clients must never supply trusted role or identity claims directly.

## Upgrade

Run the normal Velora migration for each company database. The `velora_row_policy` system table is included in system metadata migration. Existing data and existing roles are preserved; no records are rewritten.
