# Theme engine and reports

## Theme engine (`velora/theme/`)

**Principle: choose a few seed colours; derive everything else; prove it is readable.**

```
ThemeSpec (preset, brand, accent, radius, density, font, default mode, allow personal override, brand name)
      │  compile_theme()   - server side, one source of truth
      ▼
tokens for LIGHT and DARK  +  CSS  +  WCAG audit  +  Excel palette
```

- **OKLCH colour maths** (perceptual lightness) builds every tonal step; contrast is corrected by moving only *lightness*, so hue is never shifted.
- **Contrast by construction.** Body text 7:1, muted text / links / status colours / focus ring ≥ 4.5:1 (3:1 for non-text) on every surface they appear on.
  Button text is chosen per brand colour: white on a slightly deepened fill when that is a small change, near-black on light brands (cyan, amber).
  The compile result includes the full audit (40 pairs per theme) and the Theme page shows it.
- **Dark mode is derived**, not hand-written: raised surfaces (lighter = higher), lightened brand, re-checked contrast.
- **18 presets**: your 15 VIC palettes (violet, farepoint, emerald, sunset, ocean, nova, ember, midnight, verdant, arctic, forest, candy, cyan, mint, electric) plus Velora, Graphite, Ledger.
  Original VIC finding: 43 of 140 checked pairs failed WCAG AA; here 0 of 720 fail. Any custom brand colour is accepted and tuned (tested on 300 random + edge colours).
- **Density** (compact / comfortable / spacious), **corner radius** (square / soft / round) and **font** are tokens too - no per-component overrides, no `!important`.
- **Per company**: stored in `velora_setting` in each company database; only a System Manager can change it (`PUT /api/theme`). Sign-in screens use a workspace-level default (`sites/common_site_config.json` → `"theme"`).
- **Per person**: light / dark / match-device and density, remembered per user and company, unless the company turns overrides off.
- **One palette for the Desk and Excel**: the same brand drives the spreadsheet colours.

API: `GET /api/theme` · `PUT /api/theme` · `POST /api/theme/preview` (compile without saving) · `GET /api/theme/public`.

## Reports (`velora/reporting/`)

A report is a table of typed **columns** and typed **rows** - `header` (section), `data`, `subtotal`, `total`, `spacer` - each with an indent level.
Subtotal/total rows remember the rows they sum, so Excel gets real `SUM` formulas.

### 1. Script report - `<app>/<module>/report/<name>/<name>.json` + `<name>.py`
```json
{"name": "Sales by Customer Group", "module": "Demo", "type": "script", "ref_doctype": "Sales Order",
 "roles": ["System Manager", "Sales User"],
 "filters": [{"fieldname": "from_date", "label": "From Date", "fieldtype": "Date", "default": "Year Start"},
             {"fieldname": "customer_group", "label": "Customer Group", "fieldtype": "Link", "options": "Customer Group"}]}
```
```python
from velora.reporting import Column, ReportBuilder
def execute(filters):
    rb = ReportBuilder("Sales by Customer Group", [Column("name", "Customer"), Column("orders", "Orders", "Int"), Column("amount", "Amount", "Currency")])
    rb.section("Retail"); rb.row({"name": "Acme", "orders": 3, "amount": 1250.5}); rb.subtotal("Total Retail")
    rb.total("TOTAL")                       # sums the SUBTOTALS: nothing is double counted
    return rb
```

### 2. Summary report - JSON only, no code
```json
{"name": "Credit Exposure by Group", "type": "summary", "ref_doctype": "Customer", "group_by": ["customer_group", "status"],
 "measures": [{"fn": "count", "label": "Customers"}, {"fn": "sum", "field": "credit_limit", "label": "Credit Limit"}]}
```
Group by 1-2 fields, `count/sum/avg/min/max`, date buckets (`day/month/quarter/year`) via `date_field` + `date_bucket`.
Filters named `from_date`/`to_date` apply to `date_field`; other filters apply to the same-named field (or `field` / `op`). Cancelled documents never count; NULL groups show as "(none)" and sort last on every database.

### 3. Ad-hoc report - any DocType, nothing registered
`POST /api/adhoc-report/run|export` with `{"doctype", "group_by", "measures", "filters", "date_field", "date_bucket", "title"}`.
The whole definition is validated before anything runs (unknown fields, `sum` of a text field, a date bucket without a date field, bad filter shapes/operators/values, more than 20 filters).
Filters print in plain language in the report and the Excel file ("Status is not Inactive", "Credit Limit is at least 1000").

### The report builder (Desk → Reports → ＋ New report)
Pick a DocType, group by up to two fields (dates by day/month/quarter/year), add totals (count, sum, average, minimum, maximum), add filters with the same editor as the list view,
give it a title, run it, export it. **Save report** stores the *definition* only: `velora_saved_report` in the company database.
- Private by default: only the owner sees it (not even a System Manager). Only a System Manager can **share** one with the company.
- Owner or System Manager edits/deletes their own/shared reports; anyone can save a copy of a shared report.
- Running or exporting a saved report always re-checks the *current* user's permissions (read on the DocType; export for Excel), so sharing a report never shares data.
- Saved reports appear in the sidebar under **My reports** and open straight into the builder.
API: `GET/POST /api/saved-reports` · `GET/PUT/DELETE /api/saved-report/{id}` · `POST /api/saved-report/{id}/run|export`.

Definitions are validated when an app is installed (unknown DocType/field, `sum` on a text field, missing `execute()`), so mistakes fail at install, not at 9 a.m. on a Monday.
Filters are typed (Date/Select/Link/Check/number) with defaults like `Today`, `Month Start`, `Year Start`. Running needs the report's roles and **read** on its DocType; exporting also needs **export**, and every export is written to `velora_export_log`.

API: `GET /api/reports` · `GET /api/report/{name}` · `POST /api/report/{name}/run` · `POST /api/report/{name}/export`.

## The Excel export

QuickBooks-style layout in a soft palette from the company's theme:
company / title / period / filters, optional headline numbers, then the table - no gridlines, pastel header with a single confident rule colour, section rows, indented detail, subtotal rules, a double-ruled grand total.
Real numbers and dates (never text), accounting formats (negatives in parentheses, zero as a dash), real `SUM` formulas with cached values, Arial throughout, A4, fit to one page wide, header row repeats on every page, "Page x of y" footer, landscape for wide tables, frozen header (and first column when wide), document properties.
Every string is written as text, so cell content can never become a formula. Data exports from list views (header on row 1, re-importable) share the same palette and print setup.

Verified: formulas recalculated independently in LibreOffice match the cached values; the layout was rendered to images in four palettes.

## Not built yet
PDF/CSV report export, report scheduling and sharing by email, pivot/cross-tab layouts, calculated columns, charts, SQL reports, scheduled/emailed reports, logo upload, per-user theme stored on the server (personal choices live in the browser).
