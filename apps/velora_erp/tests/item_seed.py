"""Create the Inventory Items that tests reference by code (Item Code is now a validated Link)."""
from velora import get_list, new_doc


def seed_items(*codes):
    for code in codes:
        if not get_list("Inventory Item", filters={"name": code}, fields=["name"], limit=1, ignore_permissions=True):
            new_doc("Inventory Item", name=code, item_name=code, stock_uom="Each", tracking_mode="None",
                    standard_rate=1, is_stock_item=0).insert(ignore_permissions=True)
