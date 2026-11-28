# Release Notes — Velora Governance v11.6.0

## Advanced Governance Reporting

A new Governance Report Centre provides 24 reports across board governance, secretariat, compliance, risk, controls, ethics, exceptions and sustainability.

### Report list

1. Board Register & Governance Profile
2. Board & Committee Meeting Calendar
3. Meeting Quorum & Attendance
4. Board Action Register
5. Board Action Aging & Overdue
6. Board Resolution & Voting Register
7. Board Committee Register
8. Director Appointment & Term Tracker
9. Governance Obligations & Compliance Calendar
10. Compliance Assessment Results
11. Governance Risk Register
12. Control Testing & Assurance
13. Policy Review & Acknowledgement Tracker
14. Corporate Filing Tracker
15. Annual Return Status
16. Conflict of Interest Register
17. Related Party Interest Register
18. Governance Exception Register & Analysis
19. Sustainability Disclosure Readiness
20. Sustainability Data Collection Workload
21. Sustainability Targets & Progress
22. GHG Emissions Inventory
23. Materiality Assessment Status
24. Sustainability Report Lifecycle

### Measures and outputs

- Record count and status/group summaries
- Numeric totals for numeric report fields
- Due-date calculations and overdue buckets on selected reports
- Meeting quorum summary
- Sustainability readiness average
- GHG emissions totals
- CSV export and browser print

### Security

Report execution retrieves records through native permission-aware list queries. No direct unrestricted database query is used by the report API. The report source and field catalogue are allowlisted. Maximum report result size is 5,000 records per run.

### Validation

Automated tests and source-level checks passed. Live runtime installation, role testing, browser UAT and production qualification remain pending.
