from velora import Document, throw
from velora_erp.finance.validation import assert_parent, assert_no_children


class FinancialStatementRow(Document):
    def validate(self):
        self.row_code = (self.row_code or "").strip().upper()
        self.row_label = (self.row_label or "").strip()
        if not self.row_code or not self.row_label:
            throw("Row code and row label are required")
        if self.sign_multiplier not in (-1, 1):
            throw("Sign multiplier must be either -1 or 1")
        if self.row_type in ("Section", "Total") and not self.can_contain_rows:
            # Totals may be leaf totals; sections should be explicitly configured as containers.
            if self.row_type == "Section":
                throw("A Section row must be enabled to contain child rows")
        if self.row_type in ("Formula", "Account Summary") and self.can_contain_rows:
            throw("Formula and Account Summary rows cannot contain child rows")
        if self.parent_row:
            parent = assert_parent("Financial Statement Row", self.parent_row, self_name=self.name or self.row_code, group_field="can_contain_rows")
            from velora_erp.finance.validation import row
            parent_statement = row("Financial Statement Row", self.parent_row, "name", "statement_type")
            if parent_statement and parent_statement["statement_type"] != self.statement_type:
                throw("A statement row and its parent must belong to the same statement")

    def before_delete(self):
        assert_no_children("Financial Statement Row", "parent_row", self.name, "Financial statement row")
        assert_no_children("Account Statement Mapping", "statement_row", self.name, "Financial statement row")
