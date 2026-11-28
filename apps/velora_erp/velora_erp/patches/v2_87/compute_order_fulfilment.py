"""Upgrade: Purchase and Sales Orders, Purchase Receipts and Delivery Notes gain Received %, Delivered % and Billed %.

Work out the figures for every submitted document from what has already been received, delivered and invoiced, so the orders of an
existing company show the truth straight away. Safe to run again."""
from velora import get_list
from velora_erp.finance.fulfilment import REFRESH


def execute():
    for doctype, refresh in REFRESH.items():
        for row in get_list(doctype, filters=[["docstatus", "=", 1]], fields=["name"], limit=100000, ignore_permissions=True):
            refresh(row["name"])
