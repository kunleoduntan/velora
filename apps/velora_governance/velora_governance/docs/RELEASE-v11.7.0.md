# Velora Governance v11.7.0 — Reporting Visualisation & Date Filters

## Implemented
- Report Centre distribution charts using permission-aware report summaries.
- Deadline/aging charts where calculated deadline buckets exist.
- Governance Risk Register 5×5 likelihood/impact matrix heat map.
- Report-specific date-field selectors.
- Date filtering with From, To, or both bounds.
- Safe server-side report date-field whitelist.
- ISO date validation and rejection of reversed ranges.
- Numeric summary totals now ignore non-numeric values in mixed-type fields (defect found while testing the risk matrix).
- In-app User Manual and HTML report catalogue updated.

## Preserved boundaries
- Native permission-aware list retrieval.
- 5,000-record maximum per run.
- No duplicate approval/workflow engine.
- Existing SLA engine remains external.

## Qualification
Automated regression suite and static checks are local validation only. Live Velora migration, browser UAT, permission checks and data validation remain pending.
