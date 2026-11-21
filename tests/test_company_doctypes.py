from velora import site as site_mod
from velora.meta.registry import registry
from velora.settings import set_setting


def test_company_doctype_metadata_is_loaded_from_the_company_database(site):
    definition = {
        "name": "Company Local Asset", "module": "Company Custom", "fields": [
            {"fieldname": "asset_name", "label": "Asset Name", "fieldtype": "Data", "required": True},
        ],
    }
    set_setting("meta.company_doctypes", [definition])
    active_site = site_mod.current()
    active_site.load()
    assert registry.exists("Company Local Asset")
    meta = registry.get("Company Local Asset")
    assert meta.app == "company"
    assert meta.get_field("asset_name").required is True
    assert registry.controller_for("Company Local Asset")
