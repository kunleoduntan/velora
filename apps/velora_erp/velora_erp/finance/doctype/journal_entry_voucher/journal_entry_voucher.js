// "Add balancing line": when debits and credits differ, add the opposite line for the difference.
// Nothing is saved, submitted or posted by this button; the line is only added to the table for you to review.
(function () {
  function difference(doc) {
    var debit = 0, credit = 0;
    (Array.isArray(doc.lines) ? doc.lines : []).forEach(function (row) {
      var amount = Number(row.amount || 0);
      if (row.trans_effect === "Debit") debit += amount;
      else if (row.trans_effect === "Credit") credit += amount;
    });
    return Math.round((debit - credit) * 100) / 100;
  }
  velora.ui.form.on("Journal Entry Voucher", {
    refresh: function (frm) {
      if (!frm || !frm.doc || Number(frm.doc.docstatus || 0) !== 0 || typeof frm.add_table_row !== "function") return;
      var gap = difference(frm.doc);
      if (!gap) return;
      frm.add_button("Add balancing line", function () {
        var now = difference(frm.doc);
        if (!now) { velora.msgprint("The voucher already balances.", "green"); return; }
        var rows = Array.isArray(frm.doc.lines) ? frm.doc.lines : [];
        var last = rows[rows.length - 1] || {};
        frm.add_table_row("lines", {
          trans_date: last.trans_date || frm.doc.posting_date || frm.doc.voucher_date,
          transaction_description: "Balancing line",
          account_type: "Account GL",
          trans_effect: now > 0 ? "Credit" : "Debit",
          amount: Math.abs(now)
        });
        velora.msgprint("A balancing line for " + Math.abs(now).toLocaleString() + " was added. Choose its account, then save.", "info");
      });
    }
  });
})();
