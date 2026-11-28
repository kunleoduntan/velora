from ....batch import BatchDocument


class ExpenseBatch(BatchDocument):
    """Expenses paid from petty cash (or a bank account). Only money OUT is posted unless 'Also post money-in rows' is ticked."""
    BANK_FIELD = "petty_cash_account"
    DATE_FIELD = "batch_date"

    def skip_row(self, row, direction):
        return direction == "in" and not self.post_inflows
