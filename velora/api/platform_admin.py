"""Platform-administrator operations: create/clone companies and grant selected company access.
The control plane stores identity and routing only; company data is copied only when an
administrator explicitly selects DocTypes for a one-time migration into a new database.
"""
from __future__ import annotations
from fastapi import Body, FastAPI, Request, Query
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from ..exceptions import PermissionDenied, ValidationError


def install_platform_admin_routes(app: FastAPI, plane):
    from .platform import _token, _check_csrf

    def auth_for(request: Request):
        token, source = _token(request); _check_csrf(request, source)
        auth = plane.identity.resolve(token)
        if not auth.is_platform_admin:
            raise PermissionDenied("Platform administrator access is required")
        return auth

    @app.get("/api/platform/companies")
    def platform_companies(request: Request):
        auth_for(request)
        return {"data": [{k: v for k, v in c.items() if k != "secret_ref"} for c in plane.registry.list_companies()]}

    @app.get("/api/platform/pg-admin")
    def platform_pg_admin(request: Request):
        """Whether Velora already has a PostgreSQL administrator login (so the Desk need not ask for a password). Never returns the password."""
        auth_for(request)
        from .. import pgadmin
        return {"data": pgadmin.status(plane.ws)}

    @app.post("/api/platform/companies/{company_id}/status")
    def platform_company_status(company_id: str, request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        status = str(body.get("status") or "")
        if status not in ("active", "suspended"):
            raise ValidationError("status must be 'active' or 'suspended'")
        plane.registry.set_status(company_id, status, actor=auth.email)          # refuses unknown, provisioning and failed companies
        return {"data": {"id": company_id, "status": status}}

    @app.delete("/api/platform/companies/{company_id}")
    def platform_drop_company(company_id: str, request: Request, body: dict = Body(default={})):
        """Delete a company. The caller must type the company's name (`confirm`): a deleted database cannot be brought back."""
        auth = auth_for(request)
        co = plane.registry.get_company(company_id)
        if not co:
            raise ValidationError(f"No such company: {company_id}")
        if str(body.get("confirm") or "") != co["name"]:
            raise ValidationError("Type the company's exact name to confirm deleting it")
        if co["status"] == "active" and len([c for c in plane.registry.list_companies() if c["status"] == "active"]) <= 1:
            raise ValidationError("This is the only active company; create another one before deleting it")
        note = plane.provisioning.drop_company(co["id"], root_user=body.get("root_user"), root_password=body.get("root_password"), actor=auth.email)
        return {"data": {"id": co["id"], "deleted": True, "note": note}}

    @app.get("/api/platform/tenants")
    def platform_tenants(request: Request):
        auth_for(request)
        return {"data": plane.registry.list_tenants()}

    @app.post("/api/platform/tenants")
    def platform_create_tenant(request: Request, body: dict = Body(...)):
        auth_for(request)
        return {"data": plane.registry.create_tenant(str(body.get("name") or ""))}

    @app.post("/api/platform/tenants/{tenant_id}/status")
    def platform_tenant_status(tenant_id: str, request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        plane.registry.set_tenant_status(tenant_id, str(body.get("status") or ""), actor=auth.email)
        return {"data": plane.registry.get_tenant(tenant_id)}

    @app.post("/api/platform/companies")
    def platform_create_company(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        name = str(body.get("name") or "").strip()
        tenant = str(body.get("tenant_id") or "").strip()
        if not name or not tenant: raise ValidationError("Company name and tenant are required")
        result = plane.provisioning.provision_company(tenant, name, code=body.get("code"), apps=body.get("apps") or (),
            db=body.get("db", "sqlite"), db_host=body.get("db_host", "localhost"), db_port=int(body.get("db_port", 5432)),
            db_name=body.get("db_name"), db_user=body.get("db_user"), db_password=body.get("db_password"),
            root_user=body.get("root_user"), root_password=body.get("root_password"), actor=auth.email)
        _give_creator_access(auth, result.get("id"))
        return {"data": {k:v for k,v in result.items() if k not in ("secret_ref",)}}

    def _give_creator_access(auth, company_id):
        """The person who creates a company can open it straight away (otherwise it would be missing from their company list)."""
        if company_id:
            try:
                plane.identity.grant(auth.email, company_id, ["System Manager"], actor=auth.email)
            except Exception:  # noqa: BLE001 - never turn a successful create into an error; the Open button does the same later
                pass

    @app.post("/api/platform/companies/{company_id}/open")
    def platform_open_company(company_id: str, request: Request):
        """Give the calling administrator access to this company if they have none, so it appears in the company switcher."""
        auth = auth_for(request)
        co = plane.registry.get_company(company_id)
        if co is None:
            raise ValidationError("No such company")
        if co.get("status") != "active":
            raise ValidationError(f"This company is {co.get('status')}; it cannot be opened")
        if company_id not in {c["id"] for c in plane.identity.companies_for(auth.user_id)}:
            plane.identity.grant(auth.email, company_id, ["System Manager"], actor=auth.email)
        return {"data": {"id": company_id, "name": co["name"]}}

    @app.post("/api/platform/companies/{source_id}/duplicate")
    def platform_duplicate_company(source_id: str, request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        source = plane.registry.get_company(source_id)
        if not source or source.get("status") != "active": raise ValidationError("Source company does not exist or is not active")
        tenant_id = str(body.get("tenant_id") or source["tenant_id"])
        name = str(body.get("name") or "").strip()
        if not name: raise ValidationError("New company name is required")
        # The source's app set is the default. The administrator may choose a subset explicitly.
        source_site = plane.router.site_for(source)
        source_apps = source_site.installed_apps()
        apps = body.get("apps") if isinstance(body.get("apps"), list) else source_apps
        target = plane.provisioning.provision_company(tenant_id, name, code=body.get("code"), apps=apps,
            db=body.get("db", source["db_engine"]), db_host=body.get("db_host") or source.get("db_host") or "localhost",
            db_port=int(body.get("db_port") or source.get("db_port") or 5432), db_name=body.get("db_name"), db_user=body.get("db_user"),
            db_password=body.get("db_password"), root_user=body.get("root_user"), root_password=body.get("root_password"), actor=auth.email)
        _give_creator_access(auth, target.get("id"))
        sections = body.get("sections") or []
        if not isinstance(sections, list) or not all(isinstance(x, str) for x in sections): raise ValidationError("sections must be a list of section ids")
        selected = body.get("doctypes") or []
        settings_keys = body.get("settings_keys") or []
        if not isinstance(selected, list) or not all(isinstance(x, str) for x in selected): raise ValidationError("doctypes must be a list of DocType names")
        if not isinstance(settings_keys, list) or not all(isinstance(x, str) for x in settings_keys): raise ValidationError("settings_keys must be a list")
        from ..dataimport import export_data, import_file, Options
        from ..settings import get_setting, set_setting
        from .. import db
        exports = []
        for doctype in selected:
            with plane.company_scope(source["id"], user_email="Administrator", roles=("System Manager",)):
                payload, filename, _, count = export_data(doctype, "json", limit=50000)
            exports.append((doctype, payload, filename, count))
        settings_values = {}
        for key in settings_keys:
            with plane.company_scope(source["id"], user_email="Administrator", roles=("System Manager",)):
                settings_values[key] = get_setting(key)
        reports = []
        bundle = None
        if sections:
            from .. import setup_copy
            with plane.company_scope(source["id"], user_email="Administrator", roles=("System Manager",)):
                bundle = setup_copy.export_bundle(sections)
        # All selected DocTypes and selected settings are copied in one destination transaction.
        # If any import fails, no partial set of master data remains in the new company.
        try:
            with plane.company_scope(target["id"], user_email="Administrator", roles=("System Manager",)):
                if bundle is not None:                                      # the setup sections (chart of accounts, masters, workflows ...), parents first
                    res = setup_copy.apply_bundle(bundle, sections)
                    reports += [{"doctype": x["item"], "exported": x["created"], "created": x["created"], "failed": 0} for x in res["copied"] if x.get("created")]
                with db.transaction():
                    for doctype, payload, filename, count in exports:
                        report = import_file(doctype, payload, filename, Options(mode="insert", keep_names=True, atomic=True), log=False)
                        summary = {"doctype": doctype, "exported": count, "created": report.created, "failed": report.failed}
                        reports.append(summary)
                        if report.failed:
                            raise ValidationError(f"Company copy stopped at {doctype}: {report.failed} record(s) failed. The data-copy transaction was rolled back.")
                    for key, value in settings_values.items():
                        set_setting(key, value)
        except Exception as exc:
            # The new company is brand new and holds nothing but the failed copy: remove it, so no half-made company is left behind.
            plane.audit("company.duplicate_failed", actor=auth.email, subject=target["id"], detail={"source":source["id"],"error":str(exc)[:300],"doctypes":selected,"sections":sections})
            try:
                plane.provisioning.drop_company(target["id"], root_user=body.get("root_user"), root_password=body.get("root_password"), actor=auth.email)
            except Exception:  # noqa: BLE001 - if it cannot be removed, leave it marked failed so the administrator sees it
                plane.registry.update_company(target["id"], status="failed", provisioning_status="duplicate_failed", provisioning_error=str(exc)[:1000])
            raise
        plane.audit("company.duplicate", actor=auth.email, subject=target["id"], detail={"source":source["id"],"doctypes":selected,"settings":settings_keys})
        return {"data": {"company": {k:v for k,v in target.items() if k!="secret_ref"}, "source":source_id, "copied":reports, "settings_copied":settings_keys, "sections": sections}}

    @app.get("/api/platform/companies/{company_id}/copy-setup/sections")
    def platform_copy_setup_sections(company_id: str, request: Request):
        auth_for(request)
        company = plane.registry.get_company(company_id)
        if not company or company.get("status") != "active": raise ValidationError("Company does not exist or is not active")
        from .. import setup_copy
        with plane.company_scope(company_id, user_email="Administrator", roles=("System Manager",)):
            return {"data": setup_copy.sections()}

    @app.post("/api/platform/companies/{target_id}/copy-setup")
    def platform_copy_setup(target_id: str, request: Request, body: dict = Body(...)):
        """Copy setup (chart of accounts, masters, workflows, permissions) from one existing company into another, all or nothing."""
        auth = auth_for(request)
        source_id = str(body.get("source_id") or "").strip()
        sections = body.get("sections") or []
        if not source_id or source_id == target_id: raise ValidationError("Choose a different company to copy from")
        if not isinstance(sections, list) or not sections or not all(isinstance(x, str) for x in sections): raise ValidationError("Choose at least one section to copy")
        for cid in (source_id, target_id):
            company = plane.registry.get_company(cid)
            if not company or company.get("status") != "active": raise ValidationError("Both companies must exist and be active")
        from .. import setup_copy
        with plane.company_scope(source_id, user_email="Administrator", roles=("System Manager",)):
            bundle = setup_copy.export_bundle(sections)
        with plane.company_scope(target_id, user_email="Administrator", roles=("System Manager",)):
            result = setup_copy.preview(bundle, sections) if body.get("dry_run") else setup_copy.apply_bundle(bundle, sections)
        plane.audit("company.copy_setup" if not body.get("dry_run") else "company.copy_setup_preview", actor=auth.email, subject=target_id, detail={"source": source_id, "sections": sections})
        return {"data": result}

    @app.post("/api/platform/access/grant")
    def platform_grant_access(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        email = str(body.get("email") or "").strip()
        assignments = body.get("assignments") or []
        if not email or not isinstance(assignments, list) or not assignments: raise ValidationError("Email and at least one company assignment are required")
        from ..controlplane.people import People
        checked = []
        for item in assignments:                                   # check every company first: either all assignments are valid or none is made
            if not isinstance(item, dict) or not item.get("company_id") or not isinstance(item.get("roles"), list):
                raise ValidationError("Each assignment needs company_id and a roles list")
            co = plane.registry.get_company(str(item["company_id"]))
            if not co or co.get("status") != "active":
                raise ValidationError(f"Company {item['company_id']} does not exist or is not active")
            with plane.company_scope(co["id"], user_email="Administrator", roles=("System Manager",)):
                try:
                    roles = People(plane)._validate_roles(item["roles"])
                except ValidationError as exc:
                    raise ValidationError(f"{co['name']}: {exc}", advice=getattr(exc, "advice", None)) from None
            checked.append((co["id"], roles))
        if plane.identity.get_user(email) is None:
            raise ValidationError(f"There is no user {email}.", advice={"hint": "Create the person first (User administration, or People & Access inside a company), then grant access."})
        for cid, roles in checked:
            plane.identity.grant(email, cid, roles, actor=auth.email)
        assignments = [{"company_id": cid, "roles": roles} for cid, roles in checked]
        return {"data": {"email": email, "granted": assignments}}

    # ---- file explorer (platform administrators only; every rule lives in velora/filemanager.py) ----
    from ..filemanager import FileManager
    from urllib.parse import quote

    def fm():
        return FileManager(plane.ws.root)

    from .. import elevation
    from ..filemanager import CODE_ROOTS

    def console_on():
        import os
        if os.environ.get("VELORA_SERVER_CONSOLE", "on").lower() in ("off", "0", "false", "no"):
            raise PermissionDenied("The Server Console is switched off on this server (VELORA_SERVER_CONSOLE=off)")

    def need_unlock(request, auth, path):
        """Changing framework or installed-app code needs the unlocked console; the workspace's own folders do not."""
        console_on()
        parts = [x for x in str(path or "").strip("/").split("/") if x]
        if parts and parts[0] in CODE_ROOTS:
            elevation.require(plane, auth, request)

    @app.get("/api/filemanager/list")
    def fm_list(request: Request, path: str = ""):
        auth_for(request)
        return {"data": fm().list(path)}

    @app.get("/api/filemanager/read")
    def fm_read(request: Request, path: str):
        auth_for(request)
        return {"data": fm().read_text(path)}

    @app.get("/api/filemanager/download")
    def fm_download(request: Request, path: str):
        auth = auth_for(request)
        p = fm().file_for_download(path)
        plane.audit("file.download", actor=auth.email, subject=path, detail={})
        return FileResponse(p, media_type="application/octet-stream", headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(p.name), "X-Content-Type-Options": "nosniff"})

    @app.put("/api/filemanager/write")
    def fm_write(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        need_unlock(request, auth, body.get("path"))
        out = fm().write_text(str(body.get("path") or ""), body.get("content"), body.get("expected_modified"))
        plane.audit("file.edit", actor=auth.email, subject=out["path"], detail={"size": out["size"], "restart_required": out.get("restart_required", False)})
        return {"data": out}

    @app.post("/api/filemanager/new-file")
    def fm_new_file(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        need_unlock(request, auth, body.get("path"))
        out = fm().new_file(str(body.get("path") or ""), body.get("content") or "")
        plane.audit("file.create", actor=auth.email, subject=out["path"], detail={})
        return {"data": out}

    @app.post("/api/filemanager/mkdir")
    def fm_mkdir(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        need_unlock(request, auth, body.get("path"))
        out = fm().mkdir(str(body.get("path") or ""))
        plane.audit("file.mkdir", actor=auth.email, subject=out["path"], detail={})
        return {"data": out}

    @app.post("/api/filemanager/rename")
    def fm_rename(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        need_unlock(request, auth, body.get("path"))
        out = fm().rename(str(body.get("path") or ""), str(body.get("new_name") or ""))
        plane.audit("file.rename", actor=auth.email, subject=str(body.get("path")), detail={"to": out["path"]})
        return {"data": out}

    @app.post("/api/filemanager/delete")
    def fm_delete(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        need_unlock(request, auth, body.get("path"))
        out = fm().delete(str(body.get("path") or ""), recursive=bool(body.get("recursive")))
        plane.audit("file.delete", actor=auth.email, subject=out["deleted"], detail={"recursive": bool(body.get("recursive"))})
        return {"data": out}

    @app.post("/api/filemanager/upload")
    async def fm_upload(request: Request, path: str = "", overwrite: bool = False):
        """The file is the request body; its name travels in the X-Filename header (the same convention as attachments)."""
        auth = auth_for(request)
        need_unlock(request, auth, path)
        from urllib.parse import unquote
        name = unquote(request.headers.get("x-filename", ""))
        data = await request.body()
        out = fm().upload(path, name, data, overwrite=overwrite)
        plane.audit("file.upload", actor=auth.email, subject=out["path"], detail={"size": out["size"]})
        return {"data": out}

    @app.post("/api/filemanager/copy")
    def fm_copy(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        need_unlock(request, auth, body.get("to"))
        out = fm().copy(str(body.get("path") or ""), str(body.get("to") or ""))
        plane.audit("file.copy", actor=auth.email, subject=str(body.get("path")), detail={"to": out["path"]})
        return {"data": out}

    @app.get("/api/filemanager/history")
    def fm_history(request: Request, path: str):
        auth_for(request)
        return {"data": fm().history(path)}

    @app.post("/api/filemanager/restore")
    def fm_restore(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        need_unlock(request, auth, body.get("path"))
        out = fm().restore(str(body.get("path") or ""), str(body.get("version") or ""))
        plane.audit("file.restore", actor=auth.email, subject=out["path"], detail={"version": body.get("version")})
        return {"data": out}

    # ---- the Server Console: unlock, then database tools (platform administrators only; rules live in velora/elevation.py and velora/dbconsole.py) ----
    from .. import dbconsole

    @app.get("/api/console/status")
    def console_status(request: Request):
        auth = auth_for(request)
        console_on()
        return {"data": {"unlocked_for": elevation.remaining(plane, auth, request.headers.get(elevation.HEADER)), "unlock_minutes": elevation.TTL_SECONDS // 60}}

    @app.post("/api/console/unlock")
    def console_unlock(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        console_on()
        return {"data": elevation.unlock(plane, auth, str(body.get("password") or ""), body.get("totp_code"))}

    def company_or_404(company_id: str):
        co = plane.registry.get_company(company_id)
        if co is None or co["status"] != "active":
            raise ValidationError("Choose an active company")
        return co

    def console_for(auth, company_id):
        return dbconsole.DbConsole(plane.secrets.derive_key("db-console-plan"), auth.email, company_id)

    @app.get("/api/console/db/{company_id}/tables")
    def console_tables(company_id: str, request: Request):
        auth = auth_for(request)
        console_on()
        company_or_404(company_id)
        with plane.company_scope(company_id):
            data = console_for(auth, company_id).tables()
        plane.audit("db.tables", actor=auth.email, subject=company_id)
        return {"data": data}

    @app.get("/api/console/db/{company_id}/table/{table}")
    def console_table(company_id: str, table: str, request: Request, limit: int = 50, offset: int = 0, column: str | None = None, value: str | None = None,
                      order_by: str | None = None):
        auth = auth_for(request)
        console_on()
        company_or_404(company_id)
        with plane.company_scope(company_id):
            c = console_for(auth, company_id)
            out = {"structure": c.describe(table), "data": c.rows(table, limit, offset, column, value, order_by)}
        plane.audit("db.browse", actor=auth.email, subject=f"{company_id}:{table}", detail={"offset": offset, "filter": column})
        return {"data": out}

    def db_audit(auth):
        return lambda event, detail: plane.audit(event, actor=auth.email, subject=detail.get("company"), detail=detail)

    def db_backup(company_id):
        def run():
            try:
                plane.backup_company(plane.registry.get_company(company_id))
            except Exception as e:  # noqa: BLE001
                raise ValidationError(f"The safety backup could not be made, so nothing was changed: {str(e).splitlines()[0][:200]}") from None
        return run

    @app.post("/api/console/db/{company_id}/sql")
    def console_sql(company_id: str, request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        console_on()
        company_or_404(company_id)
        mode = str(body.get("mode") or "read")
        left = elevation.remaining(plane, auth, request.headers.get(elevation.HEADER))
        with plane.company_scope(company_id):
            out = console_for(auth, company_id).run(str(body.get("sql") or ""), mode, elevated=bool(left), plan=body.get("plan"),
                                                    backup=db_backup(company_id), audit=db_audit(auth))
        return {"data": out}

    @app.post("/api/console/db/{company_id}/document")
    def console_document(company_id: str, request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        console_on()
        company_or_404(company_id)
        left = elevation.remaining(plane, auth, request.headers.get(elevation.HEADER))
        with plane.company_scope(company_id):
            out = dbconsole.force_document(console_for(auth, company_id), str(body.get("doctype") or ""), str(body.get("name") or ""), str(body.get("action") or ""),
                                           str(body.get("mode") or "preview"), elevated=bool(left), confirm=str(body.get("confirm") or ""), plan=body.get("plan"),
                                           backup=db_backup(company_id), audit=db_audit(auth))
        return {"data": out}

    @app.get("/api/platform/developer-mode")
    def platform_developer_mode(request: Request):
        auth_for(request)
        return {"data": {"enabled": bool(plane.ws.common_config().get("developer_mode"))}}

    @app.put("/api/platform/developer-mode")
    def platform_set_developer_mode(request: Request, body: dict = Body(...)):
        """Developer mode lets the Desk create apps and DocType files (the DocType Creator, Application Builder). It is a workspace setting, so one switch covers every company."""
        auth = auth_for(request)
        on = body.get("enabled")
        if not isinstance(on, bool):
            raise ValidationError("enabled must be true or false")
        plane.ws.update_config(developer_mode=on)
        plane.audit("developer_mode", actor=auth.email, subject="workspace", detail={"enabled": on})
        return {"data": {"enabled": on}}

    # ---- publish to Git (platform administrators only; every rule lives in velora/gitpublish.py) ----
    from ..gitpublish import Publisher, git_available

    def pub():
        return Publisher(plane)

    @app.get("/api/publish/profiles")
    def publish_profiles(request: Request):
        auth_for(request)
        return {"data": {"profiles": pub().list(), "apps": pub().apps_here(), "git": git_available(),
                         "companies": [{"id": c["id"], "name": c["name"], "status": c["status"]} for c in plane.registry.list_companies()]}}

    @app.post("/api/publish/profiles")
    def publish_save(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        return {"data": pub().save(body, auth.email)}

    @app.delete("/api/publish/profiles/{pid}")
    def publish_delete(pid: str, request: Request):
        auth = auth_for(request)
        pub().delete(pid, auth.email)
        return {"data": {"deleted": pid}}

    @app.get("/api/publish/profiles/{pid}/status")
    def publish_status(pid: str, request: Request):
        auth_for(request)
        return {"data": pub().status(pid)}

    @app.get("/api/publish/profiles/{pid}/commands")
    def publish_commands(pid: str, request: Request):
        auth_for(request)
        return {"data": {"commands": pub().commands(pid)}}

    @app.post("/api/publish/profiles/{pid}/test")
    def publish_test(pid: str, request: Request):
        auth_for(request)
        return {"data": pub().test_connection(pid)}

    @app.post("/api/publish/profiles/{pid}/push")
    def publish_push(pid: str, request: Request, body: dict = Body(default={})):
        auth = auth_for(request)
        return {"data": pub().push(pid, str(body.get("message") or ""), auth.email, on_top=bool(body.get("on_top")))}

    @app.get("/api/publish/profiles/{pid}/compare")
    def publish_compare(pid: str, request: Request):
        """What 'Publish on top of GitHub' would add, change and remove in the repository (changes nothing)."""
        auth_for(request)
        return {"data": pub().compare(pid)}

    @app.post("/api/publish/profiles/{pid}/install")
    def publish_install(pid: str, request: Request, body: dict = Body(default={})):
        """Install / Update from GitHub: clone or fast-forward the app, install it in the profile's company, restart if configured."""
        auth = auth_for(request)
        return {"data": pub().install_from_remote(pid, auth.email, restart=body.get("restart", True) is not False)}

    @app.post("/api/publish-upload/{pid}")
    async def publish_upload(pid: str, request: Request):
        """The project zip is the request body (the same convention as the file explorer's upload)."""
        auth = auth_for(request)
        return {"data": pub().upload_zip(pid, await request.body(), auth.email)}

    # ---- Update Centre: wheels dropped in <workspace>/updates, installed with one click (rules live in velora/upgrade/dropfolder.py) ----
    from ..upgrade import dropfolder as drop
    from ..upgrade.versions import code_version, app_version

    def _update_state():
        ws = plane.ws
        files = drop.scan(ws)
        cfg = ws.common_config().get("update", {})
        return {"drop_folder": str(drop.drop_dir(ws)), "files": files, "update_available": any(f["newer"] and f["package"] for f in files),
                "current": {"velora": code_version(), "apps": {a: app_version(a) for a in ws.apps()}},
                "running": drop.running_job(ws), "last": drop.latest_job(ws), "restart_command": cfg.get("restart_command") or ""}

    @app.get("/api/update-centre")
    def update_centre(request: Request):
        auth_for(request)
        return {"data": _update_state()}

    @app.post("/api/update-centre/upload")
    async def update_upload(request: Request):
        """The wheel is the request body; its name travels in the X-Filename header."""
        auth = auth_for(request)
        from urllib.parse import unquote
        out = drop.save_upload(plane.ws, unquote(request.headers.get("x-filename", "")), await request.body())
        plane.audit("update.upload", actor=auth.email, subject=out["file"], detail={"size": out["size"]})
        return {"data": out}

    @app.post("/api/update-centre/run")
    def update_run(request: Request):
        auth = auth_for(request)
        job_id = drop.start(plane.ws, actor=auth.email)
        plane.audit("update.run", actor=auth.email, subject=job_id, detail={})
        return {"data": {"job": job_id}}

    @app.get("/api/update-centre/job/{job_id}")
    def update_job(job_id: str, request: Request):
        auth_for(request)
        job = drop.read_job(plane.ws, job_id)
        if not job:
            raise ValidationError("No such update job")
        return {"data": job}

    @app.delete("/api/update-centre/files/{name}")
    def update_remove_file(name: str, request: Request):
        auth = auth_for(request)
        f = drop.drop_dir(plane.ws) / Path(name).name
        if f.suffix != ".whl" or not f.is_file():
            raise ValidationError("No such file in the updates folder")
        f.unlink()
        plane.audit("update.remove_file", actor=auth.email, subject=f.name, detail={})
        return {"data": {"removed": f.name}}

    @app.put("/api/update-centre/settings")
    def update_settings(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        cmd = str(body.get("restart_command") or "").strip()
        if len(cmd) > 300:
            raise ValidationError("The restart command is too long")
        plane.ws.update_config(update={**plane.ws.common_config().get("update", {}), "restart_command": cmd})
        plane.audit("update.settings", actor=auth.email, subject="restart_command", detail={})
        return {"data": {"restart_command": cmd}}

    @app.get("/platform/users/manage", include_in_schema=False)
    def platform_user_admin_page():
        page = Path(__file__).resolve().parents[1] / "static" / "platform-users.html"
        return FileResponse(page, media_type="text/html")

    # Enterprise user administration (v0.35). Every endpoint resolves a live
    # control-plane session, enforces CSRF for cookie-authenticated mutations,
    # and delegates authorization to UserAdministration as a second boundary.
    from ..controlplane.user_admin import UserAdministration
    user_admin = UserAdministration(plane)

    @app.get("/api/platform/users")
    def platform_users(request: Request, q: str = Query(default=""), include_inactive: bool = True):
        auth = auth_for(request)
        rows = user_admin.list_users(auth, include_inactive=include_inactive)
        needle = q.strip().lower()
        if needle:
            rows = [r for r in rows if needle in (r.get("email") or "").lower() or needle in (r.get("full_name") or "").lower()]
        return {"data": rows}

    @app.post("/api/platform/users")
    def platform_provision_user(request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        issue = bool(body.get("issue_temporary_password"))
        made = user_admin.provision_user(auth, email=str(body.get("email") or ""), full_name=str(body.get("full_name") or ""), activate=bool(body.get("activate", False)) or issue)
        if issue:                                   # create, activate and hand over a first password in one step
            made = {**made, "is_active": True, **plane.passwords.issue_temporary(auth, made["id"])}
        return {"data": made}

    @app.patch("/api/platform/users/{user_id}")
    def platform_update_user(user_id: str, request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        return {"data": user_admin.update_profile(auth, user_id,
                    full_name=body.get("full_name"), email=body.get("email"))}

    @app.post("/api/platform/users/{user_id}/status")
    def platform_user_status(user_id: str, request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        active = body.get("active")
        if not isinstance(active, bool): raise ValidationError("active must be a boolean")
        user_admin.set_user_active(auth, user_id, active)
        return {"data": {"user_id": user_id, "is_active": active}}

    @app.get("/api/platform/users/{user_id}/memberships")
    def platform_user_memberships(user_id: str, request: Request):
        auth = auth_for(request)
        return {"data": user_admin.list_user_memberships(auth, user_id)}

    @app.post("/api/platform/users/{user_id}/memberships")
    def platform_grant_membership(user_id: str, request: Request, body: dict = Body(...)):
        auth = auth_for(request)
        company_id = str(body.get("company_id") or "")
        roles = body.get("roles") or []
        user_admin.grant_company_membership(auth, user_id, company_id, roles)
        return {"data": {"user_id": user_id, "company_id": company_id, "roles": roles}}

    @app.delete("/api/platform/users/{user_id}/memberships/{company_id}")
    def platform_revoke_membership(user_id: str, company_id: str, request: Request):
        auth = auth_for(request)
        return {"data": {"revoked": user_admin.revoke_company_membership(auth, user_id, company_id)}}

    @app.get("/api/platform/users/{user_id}/sessions")
    def platform_user_sessions(user_id: str, request: Request):
        auth = auth_for(request)
        return {"data": user_admin.list_user_sessions(auth, user_id)}

    @app.delete("/api/platform/users/{user_id}/sessions")
    def platform_revoke_all_sessions(user_id: str, request: Request):
        auth = auth_for(request)
        return {"data": {"revoked": user_admin.revoke_all_sessions(auth, user_id)}}

    @app.post("/api/platform/users/{user_id}/temporary-password")
    def platform_temporary_password(user_id: str, request: Request):
        """The password is in this one response only. The Desk shows it for a short time with a Copy button."""
        auth = auth_for(request)
        resp = JSONResponse({"data": plane.passwords.issue_temporary(auth, user_id)})
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/api/platform/password-requests")
    def platform_password_requests(request: Request):
        auth = auth_for(request)
        return {"data": plane.passwords.pending_requests(auth)}

    @app.post("/api/platform/password-requests/{request_id}/dismiss")
    def platform_dismiss_password_request(request_id: str, request: Request):
        auth = auth_for(request)
        return {"data": {"dismissed": plane.passwords.dismiss(auth, request_id)}}

    @app.get("/api/platform/email-settings")
    def platform_email_settings(request: Request):
        auth_for(request)
        cfg = plane.passwords.mail_config()
        return {"data": {"configured": cfg is not None, "host": (cfg or {}).get("host"), "from_addr": (cfg or {}).get("from_addr")}}

    @app.put("/api/platform/email-settings")
    def platform_save_email_settings(request: Request, body: dict = Body(...)):
        """Where password-reset links are sent from. The SMTP password itself is read from an environment variable, never stored here."""
        auth = auth_for(request)
        host, sender = str(body.get("host") or "").strip(), str(body.get("from_addr") or "").strip()
        if not host or "@" not in sender or len(host) > 200 or len(sender) > 254 or any(ch in sender for ch in "\r\n<>"):
            raise ValidationError("Give the SMTP host and a valid sender address")
        cfg = {"host": host, "from_addr": sender, "port": int(body.get("port") or 587), "ssl": bool(body.get("ssl")), "starttls": body.get("starttls", True) is not False,
               "user": str(body.get("user") or "").strip(), "password_env": str(body.get("password_env") or "").strip()}
        plane.ws.update_config(email=cfg)
        plane.audit("platform.email_settings", actor=auth.email, subject=host, detail={})
        return {"data": {"configured": True, "host": host, "from_addr": sender}}

    @app.post("/api/auth/mfa/setup")
    def mfa_setup(request: Request):
        token, source = _token(request); _check_csrf(request, source); auth=plane.identity.resolve(token)
        return {"data": plane.identity.begin_totp(auth)}

    @app.post("/api/auth/mfa/confirm")
    def mfa_confirm(request: Request, body: dict = Body(...)):
        token, source = _token(request); _check_csrf(request, source); auth=plane.identity.resolve(token)
        plane.identity.confirm_totp(auth, str(body.get("code") or "")); return {"data":{"enabled":True}}

    @app.post("/api/auth/mfa/disable")
    def mfa_disable(request: Request, body: dict = Body(...)):
        token, source = _token(request); _check_csrf(request, source); auth=plane.identity.resolve(token)
        plane.identity.disable_totp(auth, str(body.get("password") or "")); return {"data":{"enabled":False}}

    @app.get("/api/auth/mfa/status")
    def mfa_status(request: Request):
        token, _ = _token(request); auth=plane.identity.resolve(token); user=plane.identity.get_user(auth.email)
        return {"data":{"enabled":bool(user.get("totp_enabled"))}}
