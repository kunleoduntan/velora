from pathlib import Path

def test_financial_reporting_centre_is_integrated_into_shell():
 root=Path(__file__).parents[1]
 app=(root/"frontend/src/App.tsx").read_text()
 router=(root/"frontend/src/router.ts").read_text()
 page=root/"frontend/src/components/FinancialReportingCentre.tsx"
 assert page.exists()
 assert 'route.kind === "financial-centre"' in app
 assert 'parts[0] === "financial-centre"' in router
 assert 'api.financialLayouts()' in page.read_text()

def test_financial_reporting_centre_exposes_governed_navigation():
 source=(Path(__file__).parents[1]/"frontend/src/components/FinancialReportingCentre.tsx").read_text()
 for token in ("Financial reporting centre","Financial statements","Reporting layouts","financial-report-run","Loading"): assert token in source
