frappe.ui.form.on("Fixed Asset Component Adjustment", {
  asset(frm) { frm.set_query("component_reference", () => ({filters: {parent: frm.doc.asset, parenttype: "Fixed Asset", parentfield: "components", status: "Active"}})); }
});
