"""Runtime configuration (environment driven, overridable in code/tests)."""
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # PostgreSQL is the target database. SQLite is for zero-setup dev/tests only.
    db_url: str = "sqlite:///velora_dev.db"
    apps: list = field(default_factory=list)
    developer_mode: bool = False


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config(
            db_url=os.environ.get("VELORA_DB_URL", Config.db_url),
            apps=[a.strip() for a in os.environ.get("VELORA_APPS", "").split(",") if a.strip()],
            developer_mode=os.environ.get("VELORA_DEVELOPER_MODE", "") in ("1", "true", "yes"),
        )
    return _config


def configure(**kwargs) -> Config:
    global _config
    _config = Config(**kwargs)
    return _config
