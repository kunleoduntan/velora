import unittest
from velora_governance.governance.services.reporting_dashboard import build_reporting_dashboard

class ReportingDashboardTests(unittest.TestCase):
    def setUp(self):
        self.periods = [
            {"name": "RP-1", "period_name": "FY2026", "period_status": "Assessment", "owner": "Owner A"},
            {"name": "RP-2", "period_name": "FY2025", "period_status": "Published", "owner": "Owner B"},
        ]
        self.assessments = [
            {"reporting_period": "RP-1", "disclosure": "D1", "applicable": 1, "assessment_status": "Ready", "readiness_percent": 100},
            {"reporting_period": "RP-1", "disclosure": "D2", "applicable": 1, "assessment_status": "In Progress", "readiness_percent": 50, "gap_summary": "Evidence missing", "owner": "Owner X", "due_date": "2026-12-01"},
            {"reporting_period": "RP-2", "disclosure": "D3", "applicable": 1, "assessment_status": "Reviewed", "readiness_percent": 100},
            {"reporting_period": "RP-2", "disclosure": "D4", "applicable": 0, "assessment_status": "Not Applicable", "readiness_percent": 0},
        ]
        self.tasks = [
            {"reporting_period": "RP-1", "task_status": "Completed", "responsible_owner": "Owner A"},
            {"reporting_period": "RP-1", "task_status": "Overdue", "responsible_owner": "Owner A"},
            {"reporting_period": "RP-2", "task_status": "Open", "responsible_owner": "Owner B"},
        ]
        self.reports = [{"reporting_period": "FY2026"}, {"reporting_period": "FY2025"}]

    def test_overall_readiness_and_exclusions(self):
        result = build_reporting_dashboard(self.periods, self.assessments, self.tasks, self.reports)
        self.assertEqual(result["disclosures_total"], 3)
        self.assertEqual(result["disclosures_ready"], 2)
        self.assertEqual(result["disclosures_with_gaps"], 1)
        self.assertAlmostEqual(result["readiness_percent"], 83.33, places=2)

    def test_task_and_period_rollups(self):
        result = build_reporting_dashboard(self.periods, self.assessments, self.tasks, self.reports)
        self.assertEqual(result["tasks_total"], 3)
        self.assertEqual(result["tasks_completed"], 1)
        self.assertEqual(result["tasks_overdue"], 1)
        p1 = next(p for p in result["period_summary"] if p["name"] == "RP-1")
        self.assertEqual(p1["tasks_overdue"], 1)
        self.assertEqual(p1["disclosures_ready"], 1)

    def test_gap_list_is_disclosure_specific(self):
        result = build_reporting_dashboard(self.periods, self.assessments, self.tasks, self.reports)
        self.assertEqual([g["disclosure"] for g in result["missing_disclosures"]], ["D2"])
        self.assertEqual(result["missing_disclosures"][0]["gap_summary"], "Evidence missing")


    def test_framework_rollup(self):
        result = build_reporting_dashboard(self.periods, self.assessments, self.tasks, self.reports,
            framework_by_disclosure={"D1": "IFRS S1", "D2": "IFRS S1", "D3": "GRI"})
        frameworks = {f["framework"]: f for f in result["framework_summary"]}
        self.assertEqual(frameworks["IFRS S1"]["disclosures_total"], 2)
        self.assertEqual(frameworks["IFRS S1"]["disclosures_ready"], 1)
        self.assertEqual(frameworks["IFRS S1"]["readiness_percent"], 75.0)

    def test_owner_accountability_rollup(self):
        result = build_reporting_dashboard(self.periods, self.assessments, self.tasks, self.reports)
        owners = {o["owner"]: o for o in result["owner_summary"]}
        self.assertEqual(owners["Owner A"]["tasks_total"], 2)
        self.assertEqual(owners["Owner A"]["tasks_completed"], 1)
        self.assertEqual(owners["Owner A"]["tasks_overdue"], 1)

    def test_gap_metadata_includes_owner_and_framework(self):
        result = build_reporting_dashboard(self.periods, self.assessments, self.tasks, self.reports,
            framework_by_disclosure={"D2": "IFRS S2"})
        gap = result["missing_disclosures"][0]
        self.assertEqual(gap["owner"], "Owner X")
        self.assertEqual(gap["framework"], "IFRS S2")
        self.assertEqual(gap["due_date"], "2026-12-01")

    def test_empty_dashboard(self):
        result = build_reporting_dashboard([], [], [], [])
        self.assertEqual(result["readiness_percent"], 0)
        self.assertEqual(result["periods"], 0)
        self.assertEqual(result["missing_disclosures"], [])

if __name__ == "__main__":
    unittest.main()
