from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1] / "velora_governance"


def test_documentation_html_bundle_exists_and_has_sections():
    docs = ROOT / "docs"
    for name in (
        "INSTALLATION-v11.5.0.html",
        "USER-MANUAL-v11.5.0.html",
        "FEATURE-NOTES-v11.5.0.html",
        "governance-exception-dashboard.svg",
        "governance-exception-flow.svg",
    ):
        assert (docs / name).is_file()
    assert "velora app install" in (docs / "INSTALLATION-v11.5.0.html").read_text().lower()
    assert "governance exception centre" in (docs / "USER-MANUAL-v11.5.0.html").read_text().lower()
    feature_html = (docs / "FEATURE-NOTES-v11.5.0.html").read_text()
    assert "Governance Exception" in feature_html
    assert "Sustainability Report" in feature_html


def test_in_app_documentation_page_and_workspace_shortcut_are_registered():
    page_json = json.loads((ROOT / "page/governance_user_manual/governance_user_manual.json").read_text())
    assert page_json["page_name"] == "governance-user-manual"
    page_js = (ROOT / "page/governance_user_manual/governance_user_manual.js").read_text()
    assert "Installation Commands" in page_js
    assert "User Manual" in page_js
    assert "Feature Notes & DocTypes" in page_js
    setup = (ROOT / "setup.py").read_text()
    assert "Governance User Manual & Feature Notes" in setup


def test_feature_catalog_contains_packaged_doctype_names():
    feature_html = (ROOT / "docs/FEATURE-NOTES-v11.5.0.html").read_text()
    doctype_jsons = list((ROOT / "governance/doctype").glob("*/ *.json"))
    doctype_jsons = list((ROOT / "governance/doctype").glob("*/*.json"))
    names = [json.loads(path.read_text()).get("name") for path in doctype_jsons]
    assert len(names) == 152
    assert all(name and name in feature_html for name in names)
