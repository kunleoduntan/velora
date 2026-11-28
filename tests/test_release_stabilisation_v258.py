import re
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_erp_package_version_is_consistent():
    package = tomllib.loads((ROOT / "apps/velora_erp/pyproject.toml").read_text())
    init = (ROOT / "apps/velora_erp/velora_erp/__init__.py").read_text()
    assert f'__version__ = "{package["project"]["version"]}"' in init
    assert re.fullmatch(r"\d+\.\d+\.\d+", package["project"]["version"])


def test_pytest_import_path_includes_erp_application():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "apps/velora_erp" in config["tool"]["pytest"]["ini_options"]["pythonpath"]


def test_release_preflight_scans_metadata_and_package_contracts():
    source = (ROOT / "scripts/release_preflight.py").read_text()
    assert "DOCTYPE_JSON_PARSE" in source
    assert "ERP_TEST_IMPORT_PATH" in source
    assert "FRAMEWORK_DEPENDENCY" in source


def test_finance_request_configuration_remains_metadata_driven():
    policy = json.loads((ROOT / "apps/velora_erp/velora_erp/finance/doctype/finance_request_policy/finance_request_policy.json").read_text())
    fields = {field["fieldname"]: field for field in policy["fields"]}
    assert {"finance_roles", "manager_roles", "request_types", "priorities", "transaction_types", "approval_rules", "workflow_definition"} <= set(fields)
    api = (ROOT / "velora/api/finance_requests.py").read_text()
    assert 'or "NGN"' not in api
    assert "FINANCE_ROLES =" not in api
    assert "MANAGER_ROLES =" not in api
