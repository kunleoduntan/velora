"""Existing companies: employees see their own records and department managers see their staff's (once, editable afterwards)."""


def execute():
    from velora_erp.hr.data_protection import apply_default_field_protection, apply_employee_state_protection
    from velora_erp.hr.scopes import apply_default_scopes
    apply_default_field_protection()
    apply_employee_state_protection()
    apply_default_scopes()
