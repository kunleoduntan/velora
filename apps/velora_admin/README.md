# Velora Admin 1.9.2

Administration operations for the Velora Framework: contracts, renewals, assets, facilities, visitors, vehicles, correspondence, events and similar office administration records.

- Requires Velora >=1.16.2,<1.17.0 and VeloraERP >=2.95.4.
- 1.9.0 drops the "Administrative" prefix from its DocType names (for example *Event*, not *Administrative Event*); the upgrade patch `velora_admin.patches.v1_9.drop_administrative_prefix` renames existing records and links.
- Approvals use the framework workflow engine (GUI-defined, never hard-coded). Everything shows under Admin in the App Hub.
- Notification delivery for renewals depends on the framework Notification Engine being configured on the site.
