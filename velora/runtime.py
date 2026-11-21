from . import site as _site
from .config import Config, get_config


def init(config: Config | None = None):
    """Single-site mode: connect to one database and load the configured apps (library use, tests, simple deployments).
    Workspace deployments use sites instead (see `velora init` / `velora new-site`)."""
    cfg = config or get_config()
    site = _site.Site("default", cfg.db_url, apps=cfg.apps, developer_mode=cfg.developer_mode)
    site.load()
    _site.set_default(site)
    return cfg


def shutdown():
    _site.set_default(None)
    _site.unload_all()
