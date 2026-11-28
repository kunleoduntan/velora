# Velora 1.17.0

## Printing
- Saved print formats are now rendered with a **sandboxed Jinja2 engine** (`velora/printing_jinja.py`). Formats designed in Frappe/ERPNext render instead of showing raw `{% ... %}` / `{{ ... }}` text:
  `doc.items`, `doc.taxes`, `loop.index`, `{% if %}`, `{% for %}`, `{% set %}`, `frappe.utils.formatdate`, `frappe.utils.now_datetime`, `frappe.format_value`, `frappe.db.get_value`.
  The document is exposed as `doc` with the familiar aliases (`posting_date`, `customer_name`, `supplier_name`, `net_total`, `qty`, `item_name`, `batch_no`, `terms` ...). Plain `{{field}}` formats keep working.
- The sandbox blocks private attributes, imports and the filesystem; values are HTML-escaped. A template that does not compile is refused at save time with the line number.
- PDF output keeps tables (header row, grid, repeated header across pages) instead of flattening them to lines of text.
- **Not provided:** there is no Company document in the framework, so `frappe.db.get_value("Company", ...)` returns nothing (the format falls back to `doc.company`, which is empty). Put the company name and logo into the format itself.

## Forms
- A **warehouse chosen in the header** is copied to every item line that has a warehouse field (a line you set to another warehouse is left alone; new rows start with it). Sales Order and Purchase Order gained an optional header warehouse for this.
- **Batch picker** (`GET /api/stock/batches`): the batch field in a line offers only the batches of the line's item, in the line's warehouse, ordered **first-expiry-first-out, then first-received**; for documents that take stock out, empty and expired batches are not offered and the first is marked "use first". Documents that receive stock offer every batch of the item.
- The **+** on any link field opens the new record **in a new browser tab**; the form being edited is untouched. When the record is saved in the other tab, an empty field that was waiting for it fills itself in.
- **Email** is now a dialog with To (several addresses separated by commas), Subject and a Message. One refused recipient does not stop the others; failures are listed.

## Version
- Framework 1.17.0.
