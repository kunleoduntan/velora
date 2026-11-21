"""Tenant Registry and Company Registry."""
from __future__ import annotations

import re

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from ..exceptions import ValidationError
from . import models as m
from .identity import _now


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "company"


_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def normalize_domain(value: str) -> str:
    """A bare lower-case host name. Refuses URLs, ports, IP addresses, single words and anything that is not a valid DNS name."""
    d = (value or "").strip().lower().rstrip(".")
    if "://" in d or "/" in d or "@" in d or ":" in d or " " in d:
        raise ValidationError(f"{value!r} should be just the address, like erp.example.com (no http://, no port, no path)")
    labels = d.split(".")
    if len(d) > 253 or len(labels) < 2 or not all(_LABEL.match(x) for x in labels):
        raise ValidationError(f"{value!r} is not a valid domain name (it needs at least two parts, like example.com; letters, digits and hyphens only)")
    if re.fullmatch(r"[0-9.]+", d) or labels[-1].isdigit():
        raise ValidationError("Use a domain name, not an IP address")
    if labels[-1] in ("local", "localhost", "internal", "test", "invalid", "example"):
        raise ValidationError(f"{labels[-1]!r} addresses cannot be reached from the internet; use a real domain")
    return d


class Registry:
    def __init__(self, plane):
        self.plane = plane

    @property
    def engine(self):
        return self.plane.engine

    def _next_id(self, conn, table, prefix: str, width: int) -> str:
        n = conn.execute(select(func.count()).select_from(table)).scalar_one()
        existing = {r for r in conn.execute(select(table.c.id)).scalars()}
        n += 1
        while f"{prefix}-{n:0{width}d}" in existing:
            n += 1
        return f"{prefix}-{n:0{width}d}"

    # ---- tenants --------------------------------------------------------------------------------
    def create_tenant(self, name: str) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Tenant name is required")
        try:
            with self.engine.begin() as c:
                row = dict(id=self._next_id(c, m.tenant, "TEN", 3), name=name, status="active", created_on=_now())
                c.execute(insert(m.tenant).values(**row))
        except IntegrityError:
            raise ValidationError(f"Tenant {name!r} already exists") from None
        self.plane.audit("tenant.create", subject=row["id"], detail={"name": name})
        return row

    def get_tenant(self, ident: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(m.tenant).where((m.tenant.c.id == ident) | (m.tenant.c.name == ident))).mappings().first()
        return dict(r) if r else None

    def list_tenants(self) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(select(m.tenant).order_by(m.tenant.c.id)).mappings()]


    def set_tenant_status(self, tenant_id: str, status: str, actor: str = "cli"):
        if status not in ("active", "suspended"):
            raise ValidationError("Tenant status must be active or suspended")
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            raise ValidationError(f"No such tenant: {tenant_id}")
        with self.engine.begin() as c:
            c.execute(update(m.tenant).where(m.tenant.c.id == tenant["id"]).values(status=status))
        self.plane.audit(f"tenant.{status}", actor=actor, subject=tenant["id"])

    # ---- companies ------------------------------------------------------------------------------
    def create_company_row(self, tenant_id: str, name: str, code: str | None, **fields) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Company name is required")
        code = slug(code or name)
        try:
            with self.engine.begin() as c:
                row = dict(id=self._next_id(c, m.company, "COMP", 3), tenant_id=tenant_id, name=name, code=code, status="provisioning",
                           created_on=_now(), provisioned_db=False, **fields)
                c.execute(insert(m.company).values(**row))
        except IntegrityError:
            raise ValidationError(f"A company with code {code!r} (or this name in this tenant) already exists") from None
        return row

    def get_company(self, ident: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(m.company).where((m.company.c.id == ident) | (m.company.c.code == ident))).mappings().first()
        return dict(r) if r else None

    def list_companies(self, tenant_id: str | None = None) -> list[dict]:
        q = select(m.company, m.tenant.c.name.label("tenant_name")).join(m.tenant, m.tenant.c.id == m.company.c.tenant_id).order_by(m.company.c.id)
        if tenant_id:
            q = q.where(m.company.c.tenant_id == tenant_id)
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(q).mappings()]

    def update_company(self, company_id: str, **fields):
        with self.engine.begin() as c:
            c.execute(update(m.company).where(m.company.c.id == company_id).values(**fields))

    def set_status(self, company_id: str, status: str, actor: str = "cli"):
        if status not in ("active", "suspended"):
            raise ValidationError("Status must be active or suspended")
        co = self.get_company(company_id)
        if not co:
            raise ValidationError(f"No such company: {company_id}")
        if co["status"] in ("provisioning", "failed"):
            raise ValidationError(f"Company is {co['status']} and cannot be changed to {status}")
        self.update_company(co["id"], status=status)
        self.plane.audit(f"company.{status}", actor=actor, subject=co["id"])

    # ---- domains --------------------------------------------------------------------------------
    def add_domain(self, domain_name: str, company_id: str, *, primary: bool = False, locked: bool = True, tls: bool = False) -> dict:
        d = normalize_domain(domain_name)
        co = self.get_company(company_id)
        if co is None:
            raise ValidationError(f"No such company: {company_id}")
        try:
            with self.engine.begin() as c:
                if primary:
                    c.execute(update(m.domain).where(m.domain.c.company_id == co["id"]).values(is_primary=False))
                first = not c.execute(select(func.count()).select_from(m.domain).where(m.domain.c.company_id == co["id"])).scalar_one()
                c.execute(insert(m.domain).values(domain=d, company_id=co["id"], is_primary=primary or first, locked=locked, status="active", tls=tls, created_on=_now()))
        except IntegrityError:
            other = self.company_for_domain(d)
            raise ValidationError(f"{d} is already registered" + (f" for {other['id']}" if other and other["id"] != co["id"] else "") + ". Remove it first to move it.") from None
        return self.get_domain(d)

    def get_domain(self, domain_name: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(m.domain).where(m.domain.c.domain == (domain_name or "").strip().lower())).mappings().first()
        return dict(r) if r else None

    def list_domains(self, company_id: str | None = None) -> list[dict]:
        q = select(m.domain).order_by(m.domain.c.company_id, m.domain.c.domain)
        if company_id:
            q = q.where(m.domain.c.company_id == company_id)
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(q).mappings()]

    def remove_domain(self, domain_name: str) -> bool:
        d = (domain_name or "").strip().lower()
        with self.engine.begin() as c:
            row = c.execute(select(m.domain).where(m.domain.c.domain == d)).mappings().first()
            if not row:
                return False
            c.execute(m.domain.delete().where(m.domain.c.domain == d))
            if row["is_primary"]:                                        # another address of that company becomes the primary one
                nxt = c.execute(select(m.domain.c.domain).where(m.domain.c.company_id == row["company_id"]).order_by(m.domain.c.created_on)).scalar()
                if nxt:
                    c.execute(update(m.domain).where(m.domain.c.domain == nxt).values(is_primary=True))
        return True

    def set_domain_tls(self, domain_name: str, tls: bool) -> None:
        with self.engine.begin() as c:
            c.execute(update(m.domain).where(m.domain.c.domain == domain_name).values(tls=tls))

    def company_for_domain(self, host: str | None) -> dict | None:
        """The company an address opens (None for an unregistered address or a suspended company's... the caller decides), with the binding's `locked` flag."""
        h = (host or "").strip().lower().split(":")[0].rstrip(".")
        if not h:
            return None
        with self.engine.connect() as c:
            row = c.execute(select(m.domain).where(m.domain.c.domain == h, m.domain.c.status == "active")).mappings().first()
        if not row:
            return None
        co = self.get_company(row["company_id"])
        return None if co is None else {**co, "domain": row["domain"], "locked": bool(row["locked"])}
