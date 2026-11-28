"""Sample print formats: Receipt Voucher, Payment Voucher and Official Receipt.

They are ordinary saved print formats (Jinja), written to be edited: change the organisation name and address at the top, then
adjust the layout. Installing never overwrites a format of the same name that already exists, so your edits are safe.
"""
from __future__ import annotations

import pathlib

from velora import printing

SAMPLES = (("Receipt Voucher (sample)", "Receipt", "receipt_voucher.html"), ("Official Receipt (sample)", "Receipt", "official_receipt.html"),
           ("Payment Voucher (sample)", "Payment", "payment_voucher.html"))
_DIR = pathlib.Path(__file__).parent / "print_formats"


def install_samples() -> dict:
    existing = {(f["doctype"], f["name"]) for f in printing.listing()}
    made, kept = [], []
    for name, doctype, filename in SAMPLES:
        if (doctype, name) in existing:
            kept.append(name)
            continue
        printing.save({"name": name, "doctype": doctype, "template": (_DIR / filename).read_text(encoding="utf-8")})
        made.append(name)
    return {"installed": made, "already_there": kept}
