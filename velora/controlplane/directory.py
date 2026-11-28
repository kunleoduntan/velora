"""Company user directory: Control Plane resolves identities; role assignments are read from that company database."""
from __future__ import annotations

from sqlalchemy import select

from . import models as m


class PlaneDirectory:
    def __init__(self, plane, company_id: str):
        self.plane, self.company_id = plane, company_id

    def users_with_role(self, role: str) -> list[str]:
        with self.plane.engine.connect() as c:
            rows = c.execute(select(m.user.c.email, m.user_company.c.roles).join(m.user_company, m.user_company.c.user_id == m.user.c.id)
                             .where(m.user_company.c.company_id == self.company_id, m.user.c.is_active == True)).all()  # noqa: E712
        company = self.plane.registry.get_company(self.company_id)
        out = []
        for email, legacy_roles in rows:
            roles = self.plane.identity._company_roles(company, legacy_roles or [], user_email=email)
            if role in roles:
                out.append(email)
        return sorted(out)

    def is_user(self, user: str) -> bool:
        return self.user_email(user) is not None

    def user_email(self, user: str) -> str | None:
        if not user or "@" not in user:
            return None
        with self.plane.engine.connect() as c:
            ok = c.execute(select(m.user.c.id).where(m.user.c.email == user.lower(), m.user.c.is_active == True)).first()  # noqa: E712
        return user.lower() if ok else None
