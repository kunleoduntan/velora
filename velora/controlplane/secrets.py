"""Where database credentials live. The company registry stores only a *reference*.

  local:<id>    encrypted (Fernet/AES) in cp_secret; the master key is NOT in the database
                (VELORA_MASTER_KEY env var, or platform/master.key with mode 600)
  env:NAME      read from an environment variable   (Docker/Kubernetes secrets, systemd credentials)
  file:/path    read from a file                    (e.g. /run/secrets/...)
"""
from __future__ import annotations

import os
import secrets as _secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import insert, select

from ..document.document import now
from ..workspace import WorkspaceError
from . import models as m


def generate_master_key() -> bytes:
    return Fernet.generate_key()


def load_master_key(platform_dir: Path) -> bytes:
    env = os.environ.get("VELORA_MASTER_KEY")
    if env:
        return env.encode()
    f = platform_dir / "master.key"
    if f.exists():
        return f.read_bytes().strip()
    raise WorkspaceError("No master key: set VELORA_MASTER_KEY or restore platform/master.key (secrets cannot be decrypted without it)")


class SecretStore:
    def __init__(self, master_key: bytes, engine):
        try:
            self._fernet = Fernet(master_key)
        except Exception as e:  # noqa: BLE001
            raise WorkspaceError("The master key is not a valid Fernet key") from e
        self._engine = engine
        self._master = master_key

    def derive_key(self, purpose: str) -> bytes:
        """A key for one purpose (for example signing short-lived tokens), derived from the master key; the master key itself never leaves."""
        import hashlib, hmac
        return hmac.new(self._master, b"velora:" + purpose.encode(), hashlib.sha256).digest()

    def put(self, value: str) -> str:
        ref = "local:" + _secrets.token_hex(8)
        with self._engine.begin() as c:
            c.execute(insert(m.secret).values(ref=ref, ciphertext=self._fernet.encrypt(value.encode()).decode(), created_on=now()))
        return ref

    def get(self, ref: str) -> str:
        kind, _, key = ref.partition(":")
        if kind == "env":
            if key not in os.environ:
                raise WorkspaceError(f"Secret {ref}: environment variable {key} is not set")
            return os.environ[key]
        if kind == "file":
            p = Path(key)
            if not p.is_file():
                raise WorkspaceError(f"Secret {ref}: file not found")
            return p.read_text().strip()
        if kind == "local":
            with self._engine.connect() as c:
                row = c.execute(select(m.secret.c.ciphertext).where(m.secret.c.ref == ref)).first()
            if row is None:
                raise WorkspaceError(f"Secret {ref} does not exist")
            try:
                return self._fernet.decrypt(row[0].encode()).decode()
            except InvalidToken:
                raise WorkspaceError("Cannot decrypt the secret: wrong master key") from None
        raise WorkspaceError(f"Unknown secret reference {ref!r}")

    def delete(self, ref: str):
        if ref.startswith("local:"):
            with self._engine.begin() as c:
                c.execute(m.secret.delete().where(m.secret.c.ref == ref))
