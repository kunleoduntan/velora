from velora import Document, throw
class AttendanceSyncRun(Document):
    def validate(self):
        if self.period_start and self.period_end and str(self.period_end)<str(self.period_start): throw("Sync period end cannot precede start.")
        for field in ("records_fetched","records_created","records_skipped","records_unmapped","error_count"):
            if int(getattr(self,field,0) or 0)<0: throw("Sync counters cannot be negative.")
