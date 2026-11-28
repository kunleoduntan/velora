from velora import Document, throw

class ShareholderRegister(Document):
    def validate(self):
        seen=set(); total_percent=0.0
        for row in self.entries or []:
            key=(row.shareholder,row.share_class)
            if key in seen and row.holding_status=="Active":
                throw("A Shareholder/Share Class combination can only appear once as an active holding.")
            if row.holding_status=="Active": seen.add(key)
            if float(row.shares_held or 0)<=0:
                throw("Shares Held must be greater than zero.")
            percent=float(row.ownership_percent or 0)
            if percent<0 or percent>100:
                throw("Ownership Percent must be between 0 and 100.")
            if row.holding_status=="Active": total_percent+=percent
        if total_percent>100.0001:
            throw("Total active Shareholding Percent cannot exceed 100%.")
