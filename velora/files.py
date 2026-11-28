"""Company-isolated file and attachment storage.

Binary objects are stored outside the database; metadata and document links live in the
active company's database. The storage root is namespaced by company ID, never shared.
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import secrets
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import Response
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, insert, select, delete

from . import db, site as site_mod
from .exceptions import DoesNotExistError, PermissionDenied, ValidationError
from .permissions import get_session, check_permission, check_document_permission

MAX_FILE_BYTES = 25 * 1024 * 1024
md = MetaData()
file_record = Table(
    "vl_file", md,
    Column("id", String(32), primary_key=True),
    Column("file_name", String(255), nullable=False),
    Column("storage_key", String(500), nullable=False, unique=True),
    Column("content_type", String(180), nullable=False),
    Column("size", Integer, nullable=False),
    Column("sha256", String(64), nullable=False, index=True),
    Column("is_private", Integer, nullable=False, default=1),
    Column("attached_doctype", String(140), index=True),
    Column("attached_name", String(255), index=True),
    Column("description", Text),
    Column("uploaded_by", String(254), nullable=False),
    Column("created_on", DateTime, nullable=False),
)


def ensure():
    from .db import extra_tables; extra_tables.ensure(md)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_name(value: str) -> str:
    name = Path(str(value or "file")).name.replace("\x00", "")
    name = re.sub(r"[^A-Za-z0-9._ ()-]+", "_", name).strip(" .")
    return (name or "file")[:240]


def _workspace_files_dir(ws_root: Path) -> Path:
    """<workspace>/files/<company>: everything uploaded, in ONE well-known folder that backups include. (Before this release it was `company_files/`; renamed once, automatically.)"""
    new, old = ws_root / "files", ws_root / "company_files"
    if old.is_dir() and not new.exists():
        try:
            os.rename(old, new)
        except OSError:
            return old                                    # could not rename (permissions, another process won the race): keep using the old folder rather than lose sight of the files
    new.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(new, 0o700)
    except OSError:
        pass
    return new


def storage_root() -> Path:
    """Resolve a private storage directory that is physically separated per company."""
    site = site_mod.current()
    company_id = None
    try:
        from .company import current_company
        company_id = current_company().id
    except Exception:
        company_id = None
    configured = os.environ.get("VELORA_FILE_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
        if company_id:
            root = root / re.sub(r"[^A-Za-z0-9_.-]", "_", company_id)
        else:
            root = root / re.sub(r"[^A-Za-z0-9_.-]", "_", site.name)
    elif company_id:
        try:
            from .company import current_company
            directory = current_company().directory
            plane = getattr(directory, "plane", None)
            if plane is not None:
                root = _workspace_files_dir(Path(plane.ws.root))
            else:
                root = Path.home() / ".velora" / "company_files"
        except Exception:
            root = Path.home() / ".velora" / "company_files"
        root = root / re.sub(r"[^A-Za-z0-9_.-]", "_", company_id)
    elif site.path:
        root = Path(site.path) / "private" / "files"
    else:
        root = Path.home() / ".velora" / "files" / re.sub(r"[^A-Za-z0-9_.-]", "_", site.name)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def _path(storage_key: str) -> Path:
    root = storage_root()
    candidate = (root / storage_key).resolve()
    if root.resolve() not in candidate.parents:
        raise ValidationError("Invalid file storage key")
    return candidate


def _stage(data: bytes, storage_key: str) -> Path:
    final = _path(storage_key)
    final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = final.with_name(final.name + ".pending-" + secrets.token_hex(4))
    tmp.write_bytes(data)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    return tmp


def _commit_file(tmp: Path, storage_key: str):
    final = _path(storage_key)
    final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.replace(tmp, final)


def add_attachment(data: bytes, filename: str, *, doctype: str, docname: str, content_type: str | None = None,
                   description: str = "", migration_source: str | None = None) -> dict:
    """Attach bytes to an existing document; caller must be in a DB transaction."""
    if not isinstance(data, bytes) or not data:
        raise ValidationError("An empty file cannot be attached")
    if len(data) > MAX_FILE_BYTES:
        raise ValidationError(f"File exceeds the {MAX_FILE_BYTES // (1024*1024)} MB limit")
    from .meta.registry import registry
    meta = registry.get(doctype)
    check_document_permission(meta, "write", docname)
    from .document.document import get_doc
    get_doc(doctype, docname)
    ensure()
    safe = _safe_name(filename)
    ctype = (content_type or mimetypes.guess_type(safe)[0] or "application/octet-stream")[:180]
    fid = secrets.token_hex(16)
    storage_key = f"{fid[:2]}/{fid[2:4]}/{fid}"
    digest = hashlib.sha256(data).hexdigest()
    s = get_session()
    tmp = _stage(data, storage_key)
    row = dict(id=fid, file_name=safe, storage_key=storage_key, content_type=ctype, size=len(data),
               sha256=digest, is_private=1, attached_doctype=doctype, attached_name=docname,
               description=str(description or "")[:2000], uploaded_by=s.user, created_on=_now())
    try:
        with db.transaction() as conn:
            conn.execute(insert(file_record).values(**row))
            db.on_commit(lambda: _commit_file(tmp, storage_key))
            db.on_rollback(lambda: tmp.unlink(missing_ok=True))
    except Exception:
        try: tmp.unlink(missing_ok=True)
        except OSError: pass
        raise
    return {k: v for k, v in row.items() if k != "storage_key"}


def list_attachments(doctype: str, docname: str) -> list[dict]:
    from .meta.registry import registry
    check_document_permission(registry.get(doctype), "read", docname)
    ensure()
    with db.transaction() as conn:
        rows = conn.execute(select(file_record).where(file_record.c.attached_doctype == doctype,
            file_record.c.attached_name == docname).order_by(file_record.c.created_on)).mappings()
        return [{k: v for k, v in dict(r).items() if k != "storage_key"} for r in rows]


def get_file(file_id: str) -> tuple[dict, bytes]:
    ensure()
    with db.transaction() as conn:
        row = conn.execute(select(file_record).where(file_record.c.id == file_id)).mappings().first()
    if not row:
        raise DoesNotExistError("File not found")
    s = get_session()
    if row["attached_doctype"] and row["attached_name"]:
        from .meta.registry import registry
        check_document_permission(registry.get(row["attached_doctype"]), "read", row["attached_name"])
    elif s.user != row["uploaded_by"] and s.user != "Administrator" and "System Manager" not in s.roles:
        raise PermissionDenied("You do not have permission to access this file")
    path = _path(row["storage_key"])
    if not path.is_file():
        raise DoesNotExistError("File content is unavailable")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise ValidationError("File integrity check failed")
    return dict(row), data


def delete_attachment(file_id: str) -> dict:
    ensure()
    with db.transaction() as conn:
        row = conn.execute(select(file_record).where(file_record.c.id == file_id)).mappings().first()
        if not row:
            raise DoesNotExistError("File not found")
        from .meta.registry import registry
        if row["attached_doctype"] and row["attached_name"]:
            check_document_permission(registry.get(row["attached_doctype"]), "write", row["attached_name"])
        else:
            s = get_session()
            if s.user != row["uploaded_by"] and s.user != "Administrator" and "System Manager" not in s.roles:
                raise PermissionDenied("You cannot delete this file")
        conn.execute(delete(file_record).where(file_record.c.id == file_id))
        db.on_commit(lambda: _path(row["storage_key"]).unlink(missing_ok=True))
    return {"deleted": file_id}


def export_attachments_for_records(doctype: str, names: list[str]) -> list[tuple[dict, bytes]]:
    """Return authorized attachment bytes for the selected exported records."""
    from .meta.registry import registry
    meta = registry.get(doctype)
    check_permission(meta, "export")
    if not names:
        return []
    ensure()
    with db.transaction() as conn:
        rows = list(conn.execute(select(file_record).where(file_record.c.attached_doctype == doctype,
            file_record.c.attached_name.in_(names))).mappings())
    result = []
    for row in rows:
        check_document_permission(meta, "read", row["attached_name"])
        path = _path(row["storage_key"])
        if not path.is_file():
            raise ValidationError(f"Attachment {row['file_name']} is missing from storage")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValidationError(f"Attachment integrity check failed: {row['file_name']}")
        result.append(({k: v for k, v in dict(row).items() if k != "storage_key"}, data))
    return result


def import_attachment(data: bytes, metadata: dict) -> dict:
    """Import an attachment into an already-imported document. Caller owns transaction."""
    if len(data) > MAX_FILE_BYTES:
        raise ValidationError(f"Attachment {metadata.get('file_name')} exceeds the file size limit")
    expected = str(metadata.get("sha256") or "")
    if expected and hashlib.sha256(data).hexdigest() != expected:
        raise ValidationError(f"Attachment integrity check failed: {metadata.get('file_name')}")
    return add_attachment(data, metadata.get("file_name") or "file",
        doctype=str(metadata.get("attached_doctype") or ""),
        docname=str(metadata.get("attached_name") or ""),
        content_type=metadata.get("content_type"),
        description=metadata.get("description") or "")


def install_routes(app: FastAPI, scope, run_request):
    @app.get("/api/files")
    def files_list(request: Request, doctype: str, docname: str):
        return run_request(request, lambda: list_attachments(doctype, docname))

    @app.post("/api/files")
    async def files_upload(request: Request, doctype: str, docname: str, description: str = ""):
        data = await request.body()
        filename = request.headers.get("x-filename") or "upload.bin"
        content_type = request.headers.get("content-type") or "application/octet-stream"
        return run_request(request, lambda: add_attachment(data, filename, doctype=doctype, docname=docname,
            content_type=content_type, description=description))

    @app.get("/api/files/{file_id}")
    def files_download(file_id: str, request: Request):
        with scope(request):
            with db.transaction():
                row, data = get_file(file_id)
        filename = _safe_name(row["file_name"])
        disposition = f'attachment; filename="{filename}"'
        return Response(data, media_type=row["content_type"], headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        })

    @app.delete("/api/files/{file_id}")
    def files_delete(file_id: str, request: Request):
        return run_request(request, lambda: delete_attachment(file_id))
