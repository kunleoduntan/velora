velora.ui.form.on("Investment", {
  refresh(frm) {
    const d = frm.doc;
    if (frm.is_new()) { frm.set_intro("Choose the type of investment and enter its terms. Dates, price, expected income and the payment schedule are worked out when you save."); return; }
    if (Number(d.docstatus) !== 1) return;
    const run = (label, method, url, body, after) => frm.add_button(label, async () => {
      try { const r = await velora.api(method, url, body); velora.msgprint(after ? after(r) : "Done.", "green"); velora.reload(); }
      catch (e) { velora.msgprint(e.message || String(e), "red"); }
    });
    const base = `/api/investments/${encodeURIComponent(d.name)}`;
    if (["Active", "Part Disposed"].includes(d.status)) {
      run("Accrue income to today", "POST", `${base}/accrue`, {}, r => r.message);
      frm.add_button("Record transaction", () => velora.new_doc("Investment Transaction", { investment: d.name }));
    }
    if (d.status === "Matured") run("Roll over", "POST", `${base}/rollover`, { capitalise: false }, r => `A draft ${r.name} was created from the matured placement.`);
    frm.add_button("View portfolio", () => { window.location.hash = "#/investments"; });
    if (Number(d.docstatus) === 1) run("Reverse purchase", "POST", `${base}/reverse`, { reason: "Reversed from the investment form" }, () => "The purchase was reversed.");
  },
});
