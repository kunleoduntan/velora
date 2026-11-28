// Cost-based pricing for Inventory Item rows. Server validation remains authoritative.
(function () {
  function applyPrices(frm, onlyIndex) {
    if (!frm || !frm.doc || Number(frm.doc.docstatus || 0) !== 0) return;
    if (typeof frm.get_row_prices !== "function" || typeof frm.set_table_value !== "function") {
      frm.set_intro("Cost-based pricing and below-cost protection are enforced on the server when saved. Rebuild the Velora Desk frontend to enable live row repricing.");
      return;
    }
    var lines = Array.isArray(frm.doc.lines) ? frm.doc.lines : [];
    var selected = lines.map(function (row, index) { return { row: row, index: index }; })
      .filter(function (entry) { return entry.row.item_code && (onlyIndex === undefined || entry.index === onlyIndex); });
    if (!selected.length) return;
    frm.get_row_prices({
      customer: frm.doc.party, currency: frm.doc.currency || "NGN",
      exchange_rate: frm.doc.exchange_rate || 1,
      rows: selected.map(function (entry) {
        var row = entry.row;
        return { index: entry.index, item_code: row.item_code, uom: row.uom,
          conversion_factor: row.conversion_factor || 1, quantity: row.quantity || 1,
          discount_percentage: row.discount_percentage || 0, discount_amount: row.discount_amount || 0,
          price_basis: row.price_basis || "Automatic", warehouse: row.warehouse,
          batch: row.batch, serial_number: row.serial_number };
      })
    }).then(function (prices) {
      (prices || []).forEach(function (price) {
        var index = Number(price.index);
        if (!Number.isInteger(index) || index < 0 || index >= lines.length) return;
        if (price.manual) return;
        if (!price.priced) {
          frm.set_table_value("lines", index, "price_note", price.reason || "No configured selling price");
          return;
        }
        frm.set_table_value("lines", index, "rate", price.price);
        frm.set_table_value("lines", index, "amount", price.amount);
        frm.set_table_value("lines", index, "cost_rate", price.cost_rate);
        frm.set_table_value("lines", index, "cost_source", price.cost_source);
        frm.set_table_value("lines", index, "price_note", price.price_note);
        frm.set_table_value("lines", index, "group_price", price.group_price);
        frm.set_table_value("lines", index, "item_price", price.item_price);
        frm.set_table_value("lines", index, "default_price", price.default_price);
      });
    }).catch(function (error) {
      frm.set_intro(error && error.message ? error.message : "Selling price could not be refreshed. The server will validate the cost floor when saved.");
    });
  }
  velora.ui.form.on("Sales Invoice", {
    party: function (frm) { applyPrices(frm); },
    exchange_rate: function (frm) { applyPrices(frm); },
    currency: function (frm) { applyPrices(frm); }
  });
  velora.ui.form.on("Sales Invoice Line", {
    item_code: function (frm, row, index) { applyPrices(frm, index); },
    uom: function (frm, row, index) { applyPrices(frm, index); },
    conversion_factor: function (frm, row, index) { applyPrices(frm, index); },
    quantity: function (frm, row, index) { applyPrices(frm, index); },
    discount_percentage: function (frm, row, index) { applyPrices(frm, index); },
    discount_amount: function (frm, row, index) { applyPrices(frm, index); },
    price_basis: function (frm, row, index) { applyPrices(frm, index); },
    warehouse: function (frm, row, index) { applyPrices(frm, index); },
    batch: function (frm, row, index) { applyPrices(frm, index); },
    serial_number: function (frm, row, index) { applyPrices(frm, index); }
  });
// Inventory pricing transparency. The server returns the authoritative cost and price breakdown.
(function () {
  function explain(frm) {
    if (!frm || !frm.doc || typeof frm.get_row_prices !== "function") {
      if (frm && frm.set_intro) frm.set_intro("Price explanation is available after the Velora Desk frontend is updated.");
      return;
    }
    var rows = (frm.doc.lines || []).filter(function (row) { return row.item_code; });
    if (!rows.length) {
      frm.set_intro("Add an Inventory Item before requesting a price explanation.");
      return;
    }
    frm.get_row_prices({
      customer: frm.doc.party,
      currency: frm.doc.currency || "NGN",
      exchange_rate: frm.doc.exchange_rate || 1,
      explain_rows: rows.map(function (row) {
        return {
          item_code: row.item_code,
          uom: row.uom,
          conversion_factor: row.conversion_factor || 1,
          price_basis: row.price_basis || "Automatic",
          warehouse: row.warehouse,
          batch: row.batch,
          serial_number: row.serial_number
        };
      })
    }).then(function (results) {
      var lines = (results || []).map(function (result) {
        if (!result.applicable) return result.item_code + ": " + result.message;
        if (result.narrative && result.narrative.length) return result.item_code + " — how the price is reached\n" + result.narrative.join("\n");
        var money = function (value) {
          return value === null || value === undefined ? "Not available" :
            Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        };
        var candidates = (result.candidates || []).map(function (candidate) {
          return candidate.basis + ": " + money(candidate.price) +
            (candidate.margin_percent === null || candidate.margin_percent === undefined ? "" : " (" + candidate.margin_percent + "%)");
        });
        var chosen = result.chosen_price === null || result.chosen_price === undefined ?
          "No configured selling price" : money(result.chosen_price) + " " + result.currency;
        return result.item_code + " — Cost: " + money(result.cost_per_uom_transaction) + " " + result.currency +
          " per " + result.uom + " (" + (result.cost_source || "No cost source") + ")" +
          "; applied price: " + chosen + "; source: " + (result.price_source || result.price_reason || "Not configured") +
          (candidates.length ? "; candidates: " + candidates.join(" | ") : "");
      });
      frm.set_intro(lines.join("\n\n"));
    }).catch(function (error) {
      frm.set_intro(error && error.message ? error.message : "Could not retrieve the price explanation.");
    });
  }

  velora.ui.form.on("Sales Invoice", {
    refresh: function (frm) {
      if (typeof frm.add_button === "function") {
        frm.add_button("Explain Pricing", function () { explain(frm); });
      }
    }
  });
})();

})();
