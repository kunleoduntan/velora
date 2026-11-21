import inspect
import re
import pytest
from velora.exceptions import ValidationError
from velora.ai_tool_engine import TOOLS, _validate_args

def test_tool_catalog_has_no_arbitrary_shell_or_sql_write():
    assert "document.preview" in TOOLS
    assert "command.execute" not in TOOLS
    assert "database.execute_sql" not in TOOLS
    assert TOOLS["document.preview"]["mutating"] is True

def test_tool_args_reject_unknown_fields():
    with pytest.raises(ValidationError):
        _validate_args("doctype.inspect", {"doctype":"Customer", "sql":"DROP TABLE"})

def test_tool_args_require_mandatory_fields():
    with pytest.raises(ValidationError):
        _validate_args("doctype.inspect", {})

def test_tool_args_validate_types_and_bounds():
    with pytest.raises(ValidationError):
        _validate_args("data.query", {"doctype":"Customer", "limit":"all"})
    with pytest.raises(ValidationError):
        _validate_args("data.query", {"doctype":"Customer", "limit":1000})

def test_tool_args_valid_query():
    _validate_args("data.query", {"doctype":"Customer", "fields":["name"], "limit":20})

def test_builder_rejects_traversal_paths():
    assert re.fullmatch(r"[A-Za-z0-9_./-]{1,180}","doctype/customer/customer.json")
    assert not (re.fullmatch(r"[A-Za-z0-9_./-]{1,180}","../../etc/passwd") and ".." not in "../../etc/passwd".split("/"))

def test_migration_assistant_uses_dry_run_only():
    from velora.ai_migrations import preview_schema_migration
    assert "schema.migrate(dry_run=True)" in inspect.getsource(preview_schema_migration)
    assert "schema.migrate()" not in inspect.getsource(preview_schema_migration)
