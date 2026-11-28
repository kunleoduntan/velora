"""HTTP route of the batch picker: the batches of one item (in one warehouse) in first-expiry-first-out order."""
from fastapi import Request


def install_routes(app, scope, run):
    @app.get("/api/stock/batches")
    def stock_batches(request: Request, item_code: str = "", warehouse: str = "", txt: str = "", doctype: str = "", limit: int = 20):
        from velora_erp.finance.inventory.batch_picker import pick_batches
        return run(request, lambda: pick_batches(item_code, warehouse or None, txt, doctype or None, limit))
