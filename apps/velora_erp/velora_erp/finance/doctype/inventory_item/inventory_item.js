// Cost and margin give the selling price as you type. The server works it out again on save (same formula, same rounding).
velora.ui.form.on("Inventory Item", {
  refresh(frm) {
    frm.set_intro("Enter the cost and the selling margin: the selling price is worked out for you. Choose Fixed Price to type the price yourself.");
  },
  standard_rate: preview,
  selling_margin_percent: preview,
  pricing_mode: preview,
  standard_selling_rate: preview,
});

async function preview(frm) {
  const d = frm.doc;
  if (d.pricing_mode === "Fixed Price") { frm.set_value("calculated_selling_price", Number(d.standard_selling_rate || 0)); return; }
  const cost = Number(d.standard_rate || 0) || Number(d.last_purchase_cost || 0);
  const margin = Number(d.selling_margin_percent || 0);
  let onSelling = false, step = 0;
  try {
    const rows = await velora.api("GET", "/api/resource/Inventory%20Settings?fields=%5B%22selling_price_basis%22,%22price_rounding_step%22%5D&limit=1");
    if (rows && rows[0]) { onSelling = rows[0].selling_price_basis === "Margin on Selling Price"; step = Number(rows[0].price_rounding_step || 0); }
  } catch (e) { /* no access to the settings: the usual basis (markup on cost) is assumed */ }
  let price = 0;
  if (cost > 0 && margin >= 0 && !(onSelling && margin >= 100)) price = onSelling ? cost / (1 - margin / 100) : cost * (1 + margin / 100);
  price = step > 0 ? Math.round(price / step) * step : Math.round(price * 100) / 100;
  frm.set_value("calculated_selling_price", price);
}
