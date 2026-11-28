# Form designer, grids and the DocType Creator

## Form layouts (the Access-style designer)
A DocType's form is by default laid out by its Section/Column/Tab Break fields (stacked columns). You can instead give it a **layout**: a 12-column grid.

```json
"layout": {"tabs": [{"label": "Details", "sections": [{"label": "Customer", "collapsible": false,
   "rows": [[{"field": "customer", "span": 6}, {"field": "posting_date", "span": 3}, {"field": "due_date", "span": 3}],
            [{"field": "items", "span": 12}]]}]}]}
```
* a cell is one field with a **width of 1-12** (twelfths of the row); a row's widths add up to at most 12; a field appears once
* **no field is ever lost**: fields a layout doesn't mention are appended in a "More" section, so adding a field later can't make it vanish from the form
* tables can be placed like any field, at any width; **on a phone every cell goes full width** (short ones pair up), so one layout serves both
* a DocType with no layout renders exactly as before

**Who can change it:** a System Manager, from the form's *Customize form* button (`#/settings/layout/<DocType>`).
* **Save for everyone** stores it for this company (database-per-company: other companies keep theirs).
* **Save into the app** (developer mode only) writes the layout into the DocType's own JSON file - the one under version control. The write is atomic and changes nothing else in the file.
* **Reset** removes the company layout. The designer shows an auto-derived layout as the starting point for DocTypes that have none.

**In the designer:** drag fields from the "Not on the form" palette; drag cells between rows, sections and tabs; resize by dragging the edge, with the arrow keys, ± buttons or presets (¼ ⅓ ½ ⅔ ¾ full); equal widths per row; sections (title, collapsible, reorder) and tabs; undo/redo. Dropping into a full row shares it evenly (6/6, 4/4/4). Everything also works with buttons and the keyboard (drag-and-drop is not available on touch screens).

## Child-table grids (Frappe-v16-style)
* A child row can have **any number of fields**. The grid shows the ones you choose; **the edit button on a row opens every field**.
* **Columns:** *Columns* button: show/hide, reorder and size (a grid holds 10 width units). **Save for me** (this browser) or, for a System Manager, **Save for everyone** (or `grid_columns` in the child DocType's JSON).
* Default when nothing is configured: a small child table (up to 8 fields) shows everything, as it always did; a larger one shows the fields marked *in list view*, else the first 8.
* **Rows:** add, delete, **duplicate**, move up/down, **drag a row by its grip**; resize a column from the keyboard on its edge.

## DocType Creator
`#/settings/doctype-creator` (developer mode + System Manager) or `velora new-doctypes <app> <file|-> [--module M] [--name N] [--child] [--submittable] [--autoname-field F] [--on-conflict skip] [--dry-run]`.
Paste **Velora JSON or a Frappe DocType export** - `{"doctypes": [...]}`, one DocType, or just a list of fields. **Preview first**: it validates everything together (each DocType, then the links between them and the existing ones) and lists *all* problems; nothing is written until all are fixed. Creation is **all-or-nothing** (a failed write removes what it wrote), never overwrites an existing DocType (you choose *stop* or *skip*), and writes real files you can commit. Child tables are created first. Run `velora migrate` / `velora upgrade` to create the tables in other companies.

### What the Frappe importer maps
| Frappe | Velora |
|---|---|
| Small Text, Long Text, Text Editor, Markdown, HTML Editor, Code | Text |
| Phone, Barcode, Color, Attach, Attach Image, Autocomplete, Read Only, Signature, Icon | Data |
| Percent | Float |
| Rating, Duration, Time, Password, Dynamic Link, Geolocation, Table MultiSelect | nearest type **with a warning** saying what is approximate |
| Button, Heading, HTML | skipped, with a warning (display-only: use a client script) |
| `reqd`, `field_order` (Frappe's real order), `sort_order: "DESC"` | `required`, field order, `desc` |
| `naming_series:` / `format:PREFIX-{####}` | `series:PREFIX-.####` (date parts dropped, with a warning) |
| permissions (permlevel 0) | permissions; a default System Manager entry if none |
| `depends_on`, `mandatory_depends_on`, `fetch_from`, `allow_on_submit`, permlevel > 0 | **not supported yet** - reported per field |
| Single DocTypes (`issingle`) | **refused** with a clear message (use a normal DocType or `velora.settings`) |

## API
`GET/PUT/DELETE /api/layout/{doctype}` · `GET/PUT/DELETE /api/grid/{doctype}` · `GET /api/devtools/status` · `POST /api/devtools/doctype-creator/preview|create`. `/api/meta/{doctype}` now includes the effective `layout` / `grid_columns` and `can_customize`.

## Not built yet
Dashboards and charts; an extension SDK for custom React pages and widgets from inside an app; portals and public web pages; conditional field logic (`depends_on`) in layouts; a live preview inside the designer; and I have not yet viewed these screens in a real browser.
