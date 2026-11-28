from ....batch import BatchDocument


class BatchBankTransaction(BatchDocument):
    """Many payments (and receipts) from one bank account, as one batch."""
    BANK_FIELD = "bank_account"
    DATE_FIELD = 'batch_date'
