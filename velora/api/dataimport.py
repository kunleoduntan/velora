"""Data Import / Export endpoints (see velora/dataimport.py).

  GET  /api/data-import/{doctype}/template?format=xlsx|csv     the headings the importer understands (+ instructions)
  POST /api/data-import/{doctype}?mode=&dry_run=&submit=&atomic=&keep_names=&date_format=&match=
                                                                the file is the request body (header X-Filename gives its name); dry_run=1 checks without saving
  POST /api/data-import/errors-csv                              {"failed_rows": [...]} -> the failed rows as a CSV to fix and re-upload
  GET  /api/data-export/{doctype}?format=json|csv|xlsx&filters=[...]&limit=
"""
from __future__ import annotations

import json
import io
import zipfile
from datetime import datetime, timezone
from urllib.parse import unquote

from fastapi import Body, FastAPI, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .. import dataimport as di
from ..exceptions import ValidationError
from .. import db


def _flag(v) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


def _file(data: bytes, filename: str, ctype: str) -> Response:
    return Response(data, media_type=ctype, headers={"Content-Disposition": f'attachment; filename="{filename}"', "Access-Control-Expose-Headers": "Content-Disposition"})


def install_dataimport_routes(app: FastAPI, scope, run):
    @app.get("/api/data-import/{doctype}/template")
    def template(doctype: str, request: Request, format: str = "xlsx"):
        with scope(request):
            data, name, ctype = di.template(doctype, format)
        return _file(data, name, ctype)

    @app.post("/api/data-import/errors-csv")
    def errors_csv(request: Request, body: dict = Body(...)):
        with scope(request):
            rows = body.get("failed_rows")
            if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("data"), dict) for r in rows):
                raise ValidationError("failed_rows must be the list returned by an import")
            text = di.errors_csv({"failed_rows": rows})
        return _file(text.encode("utf-8-sig"), "import_errors.csv", "text/csv; charset=utf-8")

    @app.post("/api/data-import/errors-xlsx")
    def errors_xlsx(request: Request, body: dict = Body(...)):
        with scope(request):
            rows = body.get("failed_rows")
            if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("data"), dict) for r in rows):
                raise ValidationError("failed_rows must be the list returned by an import")
            data = di.errors_xlsx({"failed_rows": rows})
        return _file(data, "import_errors.xlsx", di._XLSX)

    @app.get("/api/grid-excel/{child}/template")
    def grid_template(child: str, request: Request):
        with scope(request):
            data, name, ctype = di.grid_export(child, None)
        return _file(data, name, ctype)

    @app.post("/api/grid-excel/{child}/export")
    def grid_export(child: str, request: Request, body: dict = Body(...)):
        rows = body.get("rows")
        if not isinstance(rows, list):
            raise ValidationError("rows must be a list")
        with scope(request):
            data, name, ctype = di.grid_export(child, rows)
        return _file(data, name, ctype)

    @app.post("/api/grid-excel/{child}/read")
    async def grid_read(child: str, request: Request, date_format: str = "DMY"):
        body = await request.body()
        filename = unquote(request.headers.get("x-filename") or "upload.xlsx")

        def work():
            with scope(request):
                return di.grid_parse(child, body, filename, date_format)
        return {"data": await run_in_threadpool(work)}

    @app.post("/api/data-import/{doctype}")
    async def import_it(doctype: str, request: Request, mode: str = "insert", dry_run: str = "0", submit: str = "0", atomic: str = "0", keep_names: str = "0",
                        date_format: str = "DMY", match: str = ""):
        body = await request.body()
        filename = unquote(request.headers.get("x-filename") or "upload")

        def work():
            with scope(request):
                opts = di.Options(mode=mode, dry_run=_flag(dry_run), submit=_flag(submit), atomic=_flag(atomic), keep_names=_flag(keep_names), date_format=date_format.upper(),
                                  match=match or None, max_rows=di.API_MAX_ROWS)
                return di.import_file(doctype, body, filename, opts).to_dict()
        return {"data": await run_in_threadpool(work)}

    @app.get("/api/data-export/{doctype}")
    def export_it(doctype: str, request: Request, format: str = "json", filters: str = "", limit: int = di.EXPORT_MAX_ROWS):
        try:
            flt = json.loads(filters) if filters else None
        except ValueError:
            raise ValidationError("filters must be JSON, like [[\"status\", \"=\", \"Active\"]]") from None
        with scope(request):
            data, name, ctype, _n = di.export_data(doctype, format, flt, limit)
        return _file(data, name, ctype)

    @app.post("/api/data-migration/package/export")
    def export_package(request: Request, body: dict = Body(...)):
        """Dynamics-style alternative: package several DocTypes in one portable ZIP with a manifest."""
        doctypes = body.get("doctypes") or []
        if not isinstance(doctypes, list) or not doctypes or not all(isinstance(x, str) for x in doctypes):
            raise ValidationError("Select one or more DocTypes to export")
        from ..settings import get_setting
        from ..permissions import get_session
        settings_keys = body.get("settings_keys") or []
        if not isinstance(settings_keys, list) or not all(isinstance(x, str) for x in settings_keys):
            raise ValidationError("settings_keys must be a list of setting names")
        include_attachments = _flag(body.get("include_attachments", "0"))
        manifest = {"format": "velora-data-package", "version": 1, "created_on": datetime.now(timezone.utc).isoformat(),
                    "company": None, "doctypes": [], "settings_keys": settings_keys, "attachments": []}
        buf = io.BytesIO()
        with scope(request):
            if settings_keys and get_session().user != "Administrator" and "System Manager" not in get_session().roles:
                from ..exceptions import PermissionDenied
                raise PermissionDenied("Only a System Manager can export company settings")
            from ..company import current_company
            try:
                co = current_company(); manifest["company"] = {"id": co.id, "name": co.name}
            except Exception: pass
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for index, doctype in enumerate(doctypes, 1):
                    payload, filename, _ctype, count = di.export_data(doctype, "json", limit=di.EXPORT_MAX_ROWS)
                    path = f"data/{index:03d}_{doctype.replace('/', '_')}.json"
                    zf.writestr(path, payload)
                    manifest["doctypes"].append({"doctype": doctype, "file": path, "count": count, "order": index})
                    if include_attachments:
                        exported = json.loads(payload.decode("utf-8"))
                        names_for_doctype = [str(row.get("name")) for row in exported.get("data", []) if row.get("name")]
                        from ..files import export_attachments_for_records
                        for file_meta, file_bytes in export_attachments_for_records(doctype, names_for_doctype):
                            attachment_path = f"attachments/{file_meta['id']}.bin"
                            zf.writestr(attachment_path, file_bytes)
                            manifest["attachments"].append({
                                "file": attachment_path, "file_name": file_meta["file_name"],
                                "content_type": file_meta["content_type"], "size": file_meta["size"],
                                "sha256": file_meta["sha256"], "attached_doctype": doctype,
                                "attached_name": file_meta["attached_name"], "description": file_meta.get("description") or ""
                            })
                settings = {key: get_setting(key) for key in manifest["settings_keys"]}
                if settings: zf.writestr("settings.json", json.dumps(settings, ensure_ascii=False, indent=2, default=str))
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return _file(buf.getvalue(), "velora_data_migration.zip", "application/zip")

    @app.post("/api/data-migration/package/import")
    async def import_package(request: Request, dry_run: str = "0"):
        payload = await request.body()
        if len(payload) > 100 * 1024 * 1024:
            raise ValidationError("Migration package exceeds the 100 MB limit")
        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
            names = set(archive.namelist())
            if "manifest.json" not in names: raise ValidationError("Migration ZIP has no manifest.json")
            expanded_size = sum(info.file_size for info in archive.infolist())
            if expanded_size > 200 * 1024 * 1024: raise ValidationError("Uncompressed migration package exceeds the 200 MB safety limit")
            manifest = json.loads(archive.read("manifest.json"))
        except (zipfile.BadZipFile, ValueError, KeyError):
            raise ValidationError("The migration package is not a valid Velora ZIP") from None
        if not isinstance(manifest, dict) or manifest.get("format") != "velora-data-package" or manifest.get("version") != 1:
            raise ValidationError("Unsupported migration package format or version")
        entries = manifest.get("doctypes") or []
        if not entries or not isinstance(entries, list): raise ValidationError("The migration package contains no DocTypes")
        manifest_settings = manifest.get("settings_keys") or []
        if not isinstance(manifest_settings, list) or not all(isinstance(x, str) for x in manifest_settings):
            raise ValidationError("Migration manifest settings_keys must be a list")
        settings_payload = None
        if "settings.json" in names:
            try: settings_payload = json.loads(archive.read("settings.json"))
            except ValueError: raise ValidationError("Migration settings.json is not valid JSON") from None
            if not isinstance(settings_payload, dict) or not all(isinstance(k, str) for k in settings_payload):
                raise ValidationError("Migration settings.json must be an object with string keys")
        # Validate every path before reading it: ZIP entries may not escape the package.
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("doctype"), str):
                raise ValidationError("Migration package contains an invalid DocType entry")
            path = entry.get("file", "")
            if not isinstance(path, str) or path.startswith("/") or ".." in path.split("/") or path not in names:
                raise ValidationError("Migration package contains an invalid data path")
        attachments = manifest.get("attachments") or []
        if not isinstance(attachments, list):
            raise ValidationError("Migration attachments must be a list")
        selected_doctypes = {entry["doctype"] for entry in entries}
        packaged_names = {}
        for entry in entries:
            try:
                exported_rows = json.loads(archive.read(entry["file"]).decode("utf-8")).get("data", [])
            except (ValueError, AttributeError):
                raise ValidationError(f"Migration data file for {entry['doctype']} is invalid JSON") from None
            if not isinstance(exported_rows, list):
                raise ValidationError(f"Migration data file for {entry['doctype']} must contain a data list")
            packaged_names[entry["doctype"]] = {str(row.get("name")) for row in exported_rows if isinstance(row, dict) and row.get("name")}
        if settings_payload is not None and set(settings_payload) != set(manifest_settings):
            raise ValidationError("Migration settings.json keys do not match manifest settings_keys")
        for attachment in attachments:
            if not isinstance(attachment, dict):
                raise ValidationError("Migration package contains an invalid attachment entry")
            apath = attachment.get("file", "")
            if not isinstance(apath, str) or apath.startswith("/") or ".." in apath.split("/") or apath not in names:
                raise ValidationError("Migration package contains an invalid attachment path")
            attached_doctype = attachment.get("attached_doctype")
            attached_name = str(attachment.get("attached_name") or "")
            if attached_doctype not in selected_doctypes or not attached_name:
                raise ValidationError("Attachment must refer to a DocType included in this migration package")
            if attached_name not in packaged_names.get(attached_doctype, set()):
                raise ValidationError("Attachment must refer to a record included in this migration package")
            if int(attachment.get("size") or -1) < 0 or int(attachment.get("size") or 0) > 25 * 1024 * 1024:
                raise ValidationError("Migration attachment size is invalid or exceeds 25 MB")
            data = archive.read(apath)
            import hashlib
            if hashlib.sha256(data).hexdigest() != str(attachment.get("sha256") or ""):
                raise ValidationError(f"Attachment checksum mismatch: {attachment.get('file_name')}")
        from ..settings import set_setting
        dry = _flag(dry_run)
        reports = []
        with scope(request):
            if dry:
                # Dry-run each DocType independently: the import engine deliberately rolls back
                # each preview, so do not wrap previews in a shared outer transaction.
                for entry in sorted(entries, key=lambda x: int(x.get("order", 0))):
                    report = di.import_file(entry["doctype"], archive.read(entry["file"]), entry["file"],
                        di.Options(mode="insert", keep_names=True, dry_run=True, atomic=True), log=False)
                    reports.append({"doctype": entry["doctype"], **report.to_dict()})
                    if report.failed: break
            else:
                # One database transaction spans every DocType. A failure in any set rolls back
                # the entire package, not just the current file.
                try:
                    with db.transaction():
                        for entry in sorted(entries, key=lambda x: int(x.get("order", 0))):
                            report = di.import_file(entry["doctype"], archive.read(entry["file"]), entry["file"],
                                di.Options(mode="insert", keep_names=True, atomic=True), log=False)
                            reports.append({"doctype": entry["doctype"], **report.to_dict()})
                            if report.failed: raise ValidationError(f"Import stopped at {entry['doctype']}: {report.failed} record(s) failed; the package was rolled back")
                        if settings_payload is not None:
                            for key, value in settings_payload.items(): set_setting(key, value)
                        if attachments:
                            from ..files import import_attachment
                            for attachment in attachments:
                                import_attachment(archive.read(attachment["file"]), attachment)
                except Exception:
                    raise
        return {"data": {"dry_run": dry, "reports": reports,
                         "settings_imported": (len(settings_payload or {}) if not dry else 0),
                         "attachments_imported": (len(attachments) if not dry else 0),
                         "attachments_validated": len(attachments)}}
