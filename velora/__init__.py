"""Velora - a metadata-driven enterprise application framework."""
from . import exceptions  # noqa: F401
from .config import configure, get_config  # noqa: F401
from .db.schema import migrate  # noqa: F401
from .document import Document, get_aggregate, get_count, get_doc, get_group_by, get_list, new_doc  # noqa: F401
from .exceptions import ValidationError  # noqa: F401
from .meta.registry import registry  # noqa: F401
from .permissions import Session, session_as  # noqa: F401
from .company import current_company  # noqa: F401
from .runtime import init, shutdown  # noqa: F401

__version__ = "1.19.2"


def throw(message: str, *, advice: dict | None = None):
    """Abort the current operation (and roll back its transaction). `advice` tells the person how to put it right (see velora.advice)."""
    raise ValidationError(message, advice=advice)


def warn(message: str, *, hint: str = "", actions: list | None = None):
    """Tell the person something without stopping the work (see velora.advice.warn)."""
    from .advice import warn as _warn
    _warn(message, hint=hint, actions=actions)
