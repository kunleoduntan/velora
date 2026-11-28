velora.ui.form.on("Fixed Asset Transfer", {
    refresh(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.history_record) {
            frm.add_custom_button(__("View Asset History"), () =>
                velora.set_route("List", "Fixed Asset History Log", {asset: frm.doc.asset})
            );
        }
    }
});
