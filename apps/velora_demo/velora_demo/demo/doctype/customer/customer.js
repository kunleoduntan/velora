velora.ui.form.on("Customer", {
  refresh(frm) {
    if (!frm.is_new() && frm.doc.status === "Blocked") {
      frm.set_intro("This customer is blocked: sales orders cannot be submitted.");
    }
    if (!frm.is_new()) {
      frm.add_button("View Orders", () => velora.navigate("Sales Order", null, { customer: frm.doc.name }));
    }
  },
  credit_limit(frm) {
    if (frm.doc.credit_limit < 0) velora.msgprint("Credit limit cannot be negative");
  },
  status(frm) {
    frm.set_read_only("credit_limit", frm.doc.status === "Blocked");
  },
});
