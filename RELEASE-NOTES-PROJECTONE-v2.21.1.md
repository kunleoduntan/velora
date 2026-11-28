# Velora ProjectOne v2.21.1 — framework field types

Requires Velora Framework `>=1.15.0,<1.16.0`.

## Changed
- Field types the framework does not have were replaced so the DocType files pass the framework's metadata check: Percent -> Float (7 fields), Small Text and Code -> Text (19 fields). 20 DocType files changed. Nothing else in ProjectOne changed; its 274 tests still pass.

## Not yet installable on a real site (found in review, not fixed here)
ProjectOne's tests use a stand-in for the host, so these only show when the framework loads the app:
1. **Six DocTypes have a field called `owner`** (Epic, Deliverable, Retrospective Action, Issue, Risk, Document Register). `owner` is the framework's system field for the creator, so the loader refuses them. The field needs a new name (for example `owner_user`) and ProjectOne's document layer must map it to and from the service-level `owner`.
2. **DocType `Project` is defined by both VeloraERP and ProjectOne**, so both cannot be installed on one site. One of them must be renamed (for example ProjectOne's to `Project Record`, or ERP's to `Finance Project`).
3. **Link targets that do not exist as DocTypes:** `User`, `Company` and `Project Contract`.
4. **`hooks.py` names `velora_projectone.setup.after_install` and `after_migrate`**, but there is no `setup` module, so installing the app would fail at that step.
5. **16 DocTypes carry a `company` field.** The framework keeps one company per database, and the standing rule is no `company` field anywhere. ProjectOne's services also pass a company/tenant id throughout (about 100 places).

Items 1 to 5 are one integration piece of work with decisions in it. They are deliberately left out of this stabilisation release.
