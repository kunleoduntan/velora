"""Framework settings stored in the current site/company database (`velora_setting`)."""
from sqlalchemy import insert, inspect, select, update
from sqlalchemy.exc import IntegrityError

from . import db
from .db.system import setting
from .document.document import now
from .permissions import get_session


def get_setting(key: str, default=None):
    with db.transaction() as conn:
        if not inspect(conn).has_table("velora_setting"):        # a site that has not run `velora migrate` yet
            return default
        row = conn.execute(select(setting.c.value).where(setting.c.key == key)).first()
    return default if row is None or row[0] is None else row[0]


def set_setting(key: str, value) -> None:
    with db.transaction() as conn:
        vals = {"value": value, "updated_by": get_session().user, "updated_on": now()}
        if conn.execute(update(setting).where(setting.c.key == key).values(**vals)).rowcount:
            return
        try:
            with conn.begin_nested():
                conn.execute(insert(setting).values(key=key, **vals))
        except IntegrityError:                                    # lost a race with another writer: update theirs
            conn.execute(update(setting).where(setting.c.key == key).values(**vals))
