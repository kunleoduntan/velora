# Velora 1.19.0: people, approvals and errors that help

- Errors that help: every error answer can carry `advice` (`hint`, `actions` with links, `field`). Framework rules cover missing fields, missing links, permissions, duplicates, stale edits, cancelled/submitted documents and linked documents. Apps add rules with the hook `error_advice`. `velora.throw(message, advice={...})` sets it directly.
- Notes that do not block: `velora.warn(message, hint=, actions=)`; returned as `warnings` with the successful answer and shown by the Desk.
- Built-in `workflow_state` on every submittable DocType, so a workflow can gate any document without Customize Form.
- People & Access: `/api/people` and the Desk page. One step to add a person (new sign-in with a one-time temporary password, or access for an existing sign-in), roles checked with suggestions, change roles, remove. Allowed to a platform administrator or the company's own System Manager; the last System Manager cannot be removed. Apps supply job profiles with the hook `access_profiles`.
- Simple workflow designer: Quick approval (one or two approvers, self-approval prevented); the approval field is chosen correctly (it used to pick a business status such as Document Status).
- Fixed: roles granted, changed or removed from the platform user screen did not reach the company database, so changes after a person's first sign-in had no effect and removed roles came back on re-adding.

No data migration: the new `workflow_state` column is added by the normal schema sync.
