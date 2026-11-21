velora.ui.form.on("Investment Transaction", {
  refresh(frm) {
    const d = frm.doc;
    if (frm.is_new()) frm.set_intro("The posting preview is worked out when you save. Income and gains follow the investment's own terms; tax is withheld as the investment's settings say.");
    if (Number(d.docstatus) === 1 && d.status === "Posted") {
      frm.add_button("Reverse", async () => {
        try { await velora.api("POST", `/api/investment-transactions/${encodeURIComponent(d.name)}/reverse`, { reason: "Reversed from the transaction form" }); velora.msgprint("The transaction was reversed.", "green"); velora.reload(); }
        catch (e) { velora.msgprint(e.message || String(e), "red"); }
      });
    }
    if (d.investment) frm.add_button("Open investment", () => velora.navigate("Investment", d.investment));
  },
});
