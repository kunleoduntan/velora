from decimal import Decimal
from velora import get_list, throw
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
D=lambda v: Decimal(str(v or 0))
def execute(filters=None):
    check_access(); filters=filters or {}
    balances=get_list("Fixed Asset Book Balance",filters={"depreciation_book":filters["depreciation_book"]} if filters.get("depreciation_book") else {},fields=["name","asset","depreciation_book","acquisition_cost","accumulated_depreciation","accumulated_impairment","carrying_amount"],limit=100000,ignore_permissions=True)
    if len(balances)>=100000: throw("Book balance report exceeds 100,000 rows. Filter by depreciation book.")
    assets={r["name"]:r for r in get_list("Fixed Asset",fields=["name","acquisition_cost","accumulated_depreciation","impairment_loss","carrying_amount","status"],limit=100000,ignore_permissions=True)}
    books={r["name"]:r for r in get_list("Fixed Asset Depreciation Book",fields=["name","book_name","book_type"],limit=10000,ignore_permissions=True)}
    rb=ReportBuilder("Fixed Asset Depreciation Book Reconciliation",[Column("asset","Fixed Asset"),Column("book","Depreciation Book"),Column("book_type","Book Type"),Column("book_carrying","Book Carrying Amount","Currency"),Column("financial_carrying","Financial Carrying Amount","Currency"),Column("temporary_difference","Book Less Financial","Currency")],subtitle="Non-financial book balances compared with the financial asset register. Tax effect calculation and deferred tax posting are not included.")
    for b in balances:
        asset=assets.get(b["asset"]); book=books.get(b["depreciation_book"])
        if not asset or not book: continue
        diff=D(b["carrying_amount"])-D(asset["carrying_amount"])
        rb.row({"asset":b["asset"],"book":book.get("book_name") or b["depreciation_book"],"book_type":book.get("book_type"),"book_carrying":D(b["carrying_amount"]),"financial_carrying":D(asset["carrying_amount"]),"temporary_difference":diff})
    return rb
