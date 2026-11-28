velora.ui.form.on("Cycle Count", {
  refresh(frm) {
    if (frm.is_new() || frm.doc.status === "Posted") {
      if (frm.doc.stock_reconciliation) frm.add_button("View Stock Reconciliation", () => velora.navigate(`/app/Stock Reconciliation/${encodeURIComponent(frm.doc.stock_reconciliation)}`));
      return;
    }
    frm.set_intro("Generate the sheet of items that are due for counting, enter what was counted, then Post Count. Differences go to a draft Stock Reconciliation for approval.");
    frm.add_button("Generate Count Sheet", async () => {
      const r = await velora.api("POST", `/api/cycle-count/${encodeURIComponent(frm.doc.name)}/generate`, {});
      velora.msgprint(`${r.count} item line(s) are due for counting.`);
      velora.reload();
    });
    frm.add_button("Post Count", async () => {
      const r = await velora.api("POST", `/api/cycle-count/${encodeURIComponent(frm.doc.name)}/post`, {});
      velora.msgprint(`Stock Reconciliation ${r.stock_reconciliation} was created for approval.`);
      velora.reload();
    });
  },
});
