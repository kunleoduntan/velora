from velora_admin.administration.universal_admin import DOCTYPES
from velora_admin.administration.operations_ui import operations_center_html


def test_renewal_register_is_available_in_universal_record_browser():
    assert DOCTYPES["renewals"] == "Renewal Register"


def test_operations_center_includes_renewal_workbench_and_delivery_notice():
    html = operations_center_html()
    assert "License, Permit & Renewal Management" in html
    assert "Renewal Register records" in html
    assert "Framework Notification Engine" in html
    assert "/api/admin/renewals/dashboard" in html
