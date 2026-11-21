"""The company a request is working in (set by the control plane; read by application code)."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CompanyInfo:
    id: str
    name: str
    tenant_id: str = ""
    tenant_name: str = ""
    directory: object | None = field(default=None, compare=False)      # who are this company's users / who holds role X (used by notifications)


_company: ContextVar[CompanyInfo | None] = ContextVar("velora_company", default=None)


def current_company() -> CompanyInfo | None:
    """None outside a company-routed request (single-site/library mode)."""
    return _company.get()


@contextmanager
def company_context(info: CompanyInfo):
    token = _company.set(info)
    try:
        yield info
    finally:
        _company.reset(token)
