"""Who are the users here, and who holds a role? Supplied by the control plane per company; a plain (library-mode) site knows nobody by role."""
from __future__ import annotations

from velora.company import current_company


class DefaultDirectory:
    """No user list is available (plain library mode): any name is accepted as a user, and nobody can be found by role."""

    def is_user(self, user: str) -> bool:
        return bool(user)

    def users_with_role(self, role: str) -> list[str]:
        return []

    def user_email(self, user: str) -> str | None:
        return user.lower() if user and "@" in user else None


DEFAULT = DefaultDirectory()


def get():
    c = current_company()
    return c.directory if c is not None and c.directory is not None else DEFAULT
