from collections import defaultdict

from velora import get_list
from velora.reporting import Column, ReportBuilder


def execute(filters):
    flt = [["docstatus", "<", 2]]
    if filters.get("from_date"):
        flt.append(["order_date", ">=", filters["from_date"]])
    if filters.get("to_date"):
        flt.append(["order_date", "<=", filters["to_date"]])
    orders = get_list("Sales Order", filters=flt, fields=["customer", "total"], limit=1000)
    groups = {c["name"]: c["customer_group"] or "(no group)" for c in get_list("Customer", fields=["name", "customer_group"], limit=1000)}
    wanted = filters.get("customer_group")

    tree = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))          # group -> customer -> [orders, amount]
    for o in orders:
        g = groups.get(o["customer"], "(no group)")
        if wanted and g != wanted:
            continue
        cell = tree[g][o["customer"]]
        cell[0] += 1
        cell[1] += float(o["total"] or 0)

    rb = ReportBuilder("Sales by Customer Group", [Column("name", "Customer"), Column("orders", "Orders", "Int"), Column("amount", "Amount", "Currency")])
    for group in sorted(tree):
        rb.section(group)
        for customer, (n, amount) in sorted(tree[group].items()):
            rb.row({"name": customer, "orders": n, "amount": amount})
        rb.subtotal(f"Total {group}")
    if tree:
        rb.total("TOTAL")
    return rb
