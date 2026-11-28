"""Developer mode from the Desk, and blank controller / client-script files for every new DocType."""
import json

from test_platform import H, PW, clean_state, login, plat  # noqa: F401  (fixtures)


def _admin(plat):
    c = plat.client()
    assert login(c, "root@example.com").status_code == 200
    return c


def test_developer_mode_switch_is_saved_audited_and_admin_only(plat):
    c = _admin(plat)
    assert c.get("/api/platform/developer-mode", headers=H).json()["data"]["enabled"] is False
    assert c.put("/api/platform/developer-mode", headers=H, json={"enabled": "yes"}).status_code == 422
    assert c.put("/api/platform/developer-mode", headers=H, json={"enabled": True}).status_code == 200
    assert json.loads(plat.ws.common_config_file.read_text())["developer_mode"] is True
    assert c.get("/api/platform/developer-mode", headers=H).json()["data"]["enabled"] is True
    a = plat.client(); login(a, "alice@example.com")
    assert a.put("/api/platform/developer-mode", headers=H, json={"enabled": False}).status_code in (401, 403)
    assert json.loads(plat.ws.common_config_file.read_text())["developer_mode"] is True


def test_creator_writes_blank_python_js_and_list_files_and_names_the_folder(plat):
    c = _admin(plat)
    c.put("/api/platform/developer-mode", headers=H, json={"enabled": True})
    r = plat.client(); login(r, "alice@example.com")
    h = {**H, "X-Velora-Company": plat.A}
    spec = {"name": "Gadget Order", "module": "Shop", "fields": [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}],
            "permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}]}
    out = r.post("/api/devtools/doctype-creator/create", headers=h, json={"json": json.dumps(spec), "app": "shop"})
    assert out.status_code == 200, out.text
    d = out.json()["data"]
    names = sorted(x.rsplit("/", 1)[-1] for x in d["files"])
    assert names == ["__init__.py", "gadget_order.js", "gadget_order.json", "gadget_order.py", "gadget_order_list.js"]
    assert d["folders"] and d["folders"][0].startswith("apps/shop/") and d["folders"][0].endswith("/gadget_order")
    folder = plat.ws.root / d["folders"][0]
    assert (folder / "gadget_order.js").read_text().startswith('velora.ui.form.on("Gadget Order"')
