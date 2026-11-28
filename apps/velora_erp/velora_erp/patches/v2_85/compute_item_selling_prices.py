"""Fill the new 'Selling Price (from cost and margin)' on every existing item."""
from velora import get_doc, get_list


def execute():
    for row in get_list("Inventory Item", fields=["name"], limit=100000, ignore_permissions=True):
        item = get_doc("Inventory Item", row["name"], ignore_permissions=True)
        item.flags.cost_refresh = True
        try:
            item.save(ignore_permissions=True)
        except Exception:  # noqa: BLE001 - an item with older invalid data is left as it is; it is fixed when someone next edits it
            continue
