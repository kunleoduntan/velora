"""Short sign-in signatures: each user keeps one short signature; when signing is switched on, approving a document appends
the approver's signature and the time to that document's signature trail (shown on the form and available to print formats)."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import Body, Request
from sqlalchemy import Column, DateTime, MetaData, String, Table, insert, select, update

from . import db
from .exceptions import ValidationError
from .permissions import get_session

md = MetaData()
user_signature = Table("vl_user_signature", md,
    Column("user_email", String(254), primary_key=True), Column("signature", String(60), nullable=False), Column("updated_on", DateTime))
document_signature = Table("vl_document_signature", md,
    Column("id", String(32), primary_key=True), Column("doctype", String(140), nullable=False, index=True),
    Column("document_name", String(255), nullable=False, index=True), Column("user_email", String(254), nullable=False),
    Column("signature", String(60), nullable=False), Column("action", String(80)), Column("signed_on", DateTime, nullable=False))


def ensure():
    from .db import extra_tables
    extra_tables.ensure(md)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def signing_enabled(doctype: str | None = None) -> bool:
    """Finance Settings ('Sign approved documents') switches signing on for the whole company; any other document can opt in
    by listing itself in a settings record that has the same field."""
    try:
        from .document.document import get_list
        rows = get_list("Finance Settings", fields=["sign_approved_documents"], limit=1, ignore_permissions=True)
        return bool(rows and rows[0].get("sign_approved_documents"))
    except Exception:  # noqa: BLE001 - the app that owns the setting is not installed
        return False


def get_signature(user: str) -> str | None:
    ensure()
    with db.transaction() as c:
        return c.execute(select(user_signature.c.signature).where(user_signature.c.user_email == user.lower())).scalar()


def set_signature(user: str, signature: str) -> dict:
    ensure()
    sig = " ".join((signature or "").split())
    if not sig or len(sig) > 40:
        raise ValidationError("A signature is 1 to 40 characters, e.g. your initials or a short name.")
    with db.transaction() as c:
        if c.execute(select(user_signature.c.user_email).where(user_signature.c.user_email == user.lower())).first():
            c.execute(update(user_signature).where(user_signature.c.user_email == user.lower()).values(signature=sig, updated_on=_now()))
        else:
            c.execute(insert(user_signature).values(user_email=user.lower(), signature=sig, updated_on=_now()))
    return {"signature": sig}


def sign(doctype: str, name: str, user: str, action: str) -> None:
    """Called after an approval step succeeds. Does nothing unless signing is on and this user has set a signature."""
    if not signing_enabled(doctype):
        return
    sig = get_signature(user)
    if not sig:
        return
    with db.transaction() as c:
        c.execute(insert(document_signature).values(id=secrets.token_hex(16), doctype=doctype, document_name=name, user_email=user.lower(),
                                                    signature=sig, action=action, signed_on=_now()))


def trail(doctype: str, name: str) -> list[dict]:
    ensure()
    with db.transaction() as c:
        rows = c.execute(select(document_signature).where(document_signature.c.doctype == doctype, document_signature.c.document_name == name)
                         .order_by(document_signature.c.signed_on)).mappings().all()
    return [{"user": r["user_email"], "signature": r["signature"], "action": r["action"], "signed_on": r["signed_on"].strftime("%d/%m/%Y %H:%M")} for r in rows]


def install_routes(app, scope, run):
    @app.get("/api/me/signature")
    def my_signature(request: Request):
        return run(request, lambda: {"signature": get_signature(get_session().user)})

    @app.put("/api/me/signature")
    def save_my_signature(request: Request, body: dict = Body(...)):
        return run(request, lambda: set_signature(get_session().user, str(body.get("signature", ""))))

    @app.get("/api/signatures/{doctype}/{name}")
    def document_trail(doctype: str, name: str, request: Request):
        def go():
            from .document.document import get_doc
            get_doc(doctype, name)                               # whoever may read the document may see who signed it
            return trail(doctype, name)
        return run(request, go)
