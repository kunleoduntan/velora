# Velora framework 1.13.0

## Cancel the ERPNext way: linked-documents check and Cancel All
- A submitted document can no longer be cancelled while **another submitted document still points at it** (Link field in the document or in a child table, plus plain-field links an app declares). The error names them ("Cancel Delivery Note DN-0004 first").
- A controller lists what it unlinks or removes by itself in `ignore_linked_doctypes`, so those do not block the cancel.
- New hook `linked_documents_provider` (a module with `dynamic_links(doctype, name)`) for apps that keep links in `source_doctype` + `source_document` style fields.
- New API: `GET /api/linked-documents/{doctype}/{name}` (what depends on it, in cancel order) and `POST /api/cancel-all/{doctype}/{name}` (cancel the whole chain, newest first, in one transaction: all or nothing; a missing cancel permission names the document).
- `doc_events` accepts `"*"` for every document type, which is how an app registers one cancel routine for all its documents.
- The Desk Cancel button opens a dialog: reason (required), the list of dependent documents, Cancel Document / Cancel All.

## System records
- A DocType can set `"hide_from_menu": true`: kept in the database, shown in no sidebar.

## From 1.12.6 (unchanged here)
- SQLite WAL mode and the 15-second limit on link / search requests.

## Honest limits
- Tested on SQLite only; the PostgreSQL run is still outstanding.
