from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "velora_governance"


def test_exception_dashboard_calls_permission_aware_analytics_api():
    js = (ROOT / "page/governance_exception_centre/governance_exception_centre.js").read_text()
    assert "get_governance_exception_analytics" in js
    assert "severity_counts" in js
    assert "owner_counts" in js
    assert "aging_buckets" in js
    assert "integration_state" in js


def test_dashboard_has_responsive_kpi_and_chart_styles():
    css = (ROOT / "page/governance_exception_centre/governance_exception_centre.css").read_text()
    assert "exception-kpi-grid" in css
    assert "exception-analytics-grid" in css
    assert "@media(max-width:600px)" in css


def test_dashboard_does_not_implement_sla_engine():
    js = (ROOT / "page/governance_exception_centre/governance_exception_centre.js").read_text()
    assert "SLA metrics are only displayed when supplied by the existing SLA engine" in js
    assert "calculate_sla" not in js
