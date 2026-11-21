import velora
from velora import new_doc
from velora_erp.setup import after_install


def _site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'s.db'}", apps=["velora_erp"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()


def test_search_finds_by_code_and_by_name_and_shows_a_human_title(tmp_path):
    _site(tmp_path)
    try:
        from velora.api.search import _fallback_query
        new_doc("Employee", employee_code="EMP-77", employee_name="Ngozi Okafor").insert(ignore_permissions=True)
        by_code = _fallback_query("emp-77", 10)
        by_name = _fallback_query("ngozi okafor", 10)
        assert by_code and by_code[0]["doctype"] == "Employee" and by_code[0]["title"] == "Ngozi Okafor"
        assert by_name and by_name[0]["name"] == "EMP-77"
        assert _fallback_query("no-such-thing-xyz", 10) == []
    finally:
        velora.shutdown()


def test_search_is_time_boxed_and_never_errors(tmp_path, monkeypatch):
    _site(tmp_path)
    try:
        from velora.api import search
        monkeypatch.setattr(search, "BUDGET_SECONDS", 0)
        assert search._fallback_query("anything", 10) == []
    finally:
        velora.shutdown()
