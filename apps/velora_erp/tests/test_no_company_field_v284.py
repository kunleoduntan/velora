"""No doctype carries a `company` field: every company has its own database, so the stamp was meaningless and was removed."""
import glob, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_doctype_has_a_company_field():
    offenders = []
    for path in glob.glob(f"{ROOT}/velora_erp/**/doctype/*/*.json", recursive=True):
        data = json.load(open(path))
        for field in data.get("fields", []) or []:
            if field.get("fieldname") == "company":
                offenders.append(os.path.relpath(path, ROOT))
    assert not offenders, f"These doctypes still have a company field: {offenders}"


def test_no_hook_stamps_a_company():
    text = open(f"{ROOT}/velora_erp/hooks.py").read()
    assert "fill_default_company" not in text
