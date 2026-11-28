# Velora 1.18.0

- Create From may open a form unsaved: a document-flow provider can return `{"prefill": True, "doctype": ..., "values": {...}}`; the API answers with `name: null` and the values, and the Desk opens a new form filled with them ("Started from ..."). Nothing is created until the user saves.
- Workflows: a failing approval-policy or template provider, or an unreadable frozen definition, is logged (logger `velora.workflows`) instead of being ignored silently.
- Deprecated `datetime.utcnow()` calls replaced in the apps shipped with the framework.
- Governance: two document types that had no permissions (Sustainability Report Publication, Sustainability Report Export Template) now follow Sustainability Report.

Requires no data migration. Packaged with VeloraERP 2.105.0.
