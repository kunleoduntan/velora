# Velora Governance 11.9.0: running on the Velora framework
Governance code is unchanged in behaviour; a thin adapter (`runtime.py`, a frappe-like facade over Velora) lets it run on Velora with VeloraERP, ProjectOne and Admin installed.
- **No name clashes**: all 129 DocTypes (101 documents, the rest child tables) were checked against the other apps. Changes needed to load: unsupported field types became Text; `fixed:` naming became prompt/field naming; fields called `owner` were renamed (a system field); links to a User DocType became plain text (users live in the control plane); single DocTypes became ordinary documents with one fixed name (`default`).
- **No duplicated functions**: Excel export uses the framework's `report_to_xlsx`; notifications go to Velora Notify's Notification Log through the adapter; users resolve through the company directory.
- One HTTP route (`/api/governance/call/{function}`) runs only functions Governance marked callable, each checking the caller's permissions.
- Screens: Governance hub (sections for all 101 documents) and the Governance centre (`#/governance/...`). The old Frappe `page/*` scripts are not used by the Velora desk.
- Requires Velora >=1.16.2.
