"""A safe file explorer for the workspace folder (the Desk's "Files" screen, for platform administrators).

What it shows (and what each folder allows):
    apps/     read, edit, upload, new folder, rename, delete     (the code of installed apps)
    files/    read, edit, upload, new folder, rename, delete     (uploaded attachments)
    backups/  read, download, delete
    logs/     read, download, delete
    framework/  the Velora framework's own code      read; edit and upload need the console to be unlocked (no rename, no delete)
    installed/  the code of installed apps (VeloraERP ...)  read; edit and upload need the console to be unlocked (no rename, no delete)
Every overwrite or deletion of code first keeps the old version in backups/file-history, and a .py or .json file that does not parse is refused.
Never reachable, however the path is written: `platform/` (master key, control plane), `config/` (settings and secrets), the install folder around the workspace
(it holds the database administrator's password), and any file that looks like a secret (.env, *.key, *.pem, *password*, *secret*, private keys).

Every path is checked here, not in the browser: it must be relative, free of `..`, NUL bytes and backslashes, start with one of the four folders, and contain no symbolic link
anywhere along the way (so a link inside `apps/` cannot lead out of the workspace). Writes are atomic (a temporary file, then a rename).
"""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import sys
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .exceptions import PermissionDenied, ValidationError

ROOTS = {"apps": {"edit", "delete"}, "files": {"edit", "delete"}, "backups": {"delete"}, "logs": {"delete"}, "framework": {"edit"}, "installed": {"edit"}}
CODE_ROOTS = {"framework", "installed"}            # editing here changes the running product: it needs the unlocked console and a restart
HISTORY_ROOTS = {"apps", "framework", "installed"}
HISTORY_KEEP = 25
MAX_EDIT_BYTES = 512 * 1024
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_NAME = 200
TEXT_SUFFIXES = {".py", ".json", ".js", ".ts", ".tsx", ".jsx", ".css", ".html", ".md", ".txt", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".csv", ".xml", ".svg", ".sh", ".sql", ".log", ".rst", ".env.example", ""}
SECRET_PATTERNS = (".env", ".env.*", "*.key", "*.pem", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "*password*", "*secret*", "*credential*", ".netrc", ".pgpass")
BAD_NAME = re.compile(r'[\x00-\x1f\\/:*?"<>|]')


def _is_secret(name: str) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, p) for p in SECRET_PATTERNS) and not low.endswith(".env.example")


def _clean_name(name: str) -> str:
    name = str(name or "").strip()
    if not name or name in (".", "..") or len(name) > MAX_NAME or BAD_NAME.search(name) or name.startswith(" ") or name.endswith("."):
        raise ValidationError("That name is not allowed (no slashes, no control characters, at most 200 characters)")
    if _is_secret(name):
        raise PermissionDenied("Files that look like secrets (keys, passwords, .env) cannot be created or opened here")
    return name


class FileManager:
    def __init__(self, workspace_root):
        self.root = Path(workspace_root).resolve()

    # ---- where each top-level folder really lives ------------------------------------------------------------------------------------------
    def installed_apps(self) -> dict[str, Path]:
        """Installed Velora apps (a package with a hooks.py) found where Python imports from, other than the framework itself."""
        found: dict[str, Path] = {}
        for entry in sys.path:
            d = Path(entry or ".")
            if not d.is_dir():
                continue
            try:
                names = sorted(os.listdir(d))
            except OSError:
                continue
            for n in names:
                if n.startswith("velora_") and n not in found and (d / n / "hooks.py").is_file() and not (d / n).is_symlink():
                    found[n] = (d / n).resolve()
        return found

    @staticmethod
    def framework_path() -> Path:
        import velora
        return Path(velora.__file__).resolve().parent

    def base_for(self, parts: list[str]) -> tuple[Path, int]:
        """The real folder behind the first part(s) of a path, and how many parts it consumed."""
        if parts[0] == "framework":
            return self.framework_path(), 1
        if parts[0] == "installed":
            if len(parts) < 2:
                return self.root, 1
            apps = self.installed_apps()
            if parts[1] not in apps:
                raise ValidationError("Not found")
            return apps[parts[1]], 2
        return self.root / parts[0], 1

    # ---- path safety -----------------------------------------------------------------------------------------------------------------------
    def parts(self, rel: str) -> list[str]:
        rel = str(rel or "").strip().strip("/")
        if "\x00" in rel or "\\" in rel or rel.startswith("~"):
            raise ValidationError("Invalid path")
        parts = [p for p in rel.split("/") if p != ""]
        if any(p in (".", "..") for p in parts):
            raise ValidationError("Invalid path")
        if parts and parts[0] not in ROOTS:
            raise PermissionDenied("This folder cannot be opened here")
        for p in parts:
            if _is_secret(p):
                raise PermissionDenied("Files that look like secrets cannot be opened here")
        return parts

    def resolve(self, rel: str, *, must_exist: bool = True) -> Path:
        parts = self.parts(rel)
        if not parts:
            return self.root
        if parts[0] in CODE_ROOTS:
            base, used = self.base_for(parts)
            walk = parts[used:]
        else:
            base, walk = self.root, parts
        cur = base
        for i, part in enumerate(walk):
            cur = cur / part
            try:
                st = cur.lstat()
            except FileNotFoundError:
                if must_exist or i < len(walk) - 1:
                    raise ValidationError("Not found") from None
                return cur
            if stat.S_ISLNK(st.st_mode):
                raise PermissionDenied("Symbolic links cannot be followed here")
        if cur != base and base not in cur.parents:
            raise PermissionDenied("Outside the allowed folder")
        return cur

    def can(self, rel: str, action: str) -> bool:
        parts = self.parts(rel)
        return bool(parts) and action in ROOTS[parts[0]]

    def _require(self, rel: str, action: str):
        if not self.can(rel, action):
            raise PermissionDenied(f"{action.capitalize()} is not allowed in this folder")
        top = self.root / self.parts(rel)[0]
        if action == "edit" and self.parts(rel)[0] not in CODE_ROOTS and not top.exists() and not top.is_symlink():
            top.mkdir()                                                      # a workspace that has not used this folder yet

    @staticmethod
    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")

    # ---- reading ---------------------------------------------------------------------------------------------------------------------------
    def list(self, rel: str = "") -> dict:
        parts = self.parts(rel)
        if not parts:
            entries = []
            for name in ROOTS:
                d = self.framework_path() if name == "framework" else self.root / name
                entries.append({"name": name, "type": "dir", "size": None, "modified": self._iso(d.stat().st_mtime) if d.is_dir() else None, "editable": False,
                                "can_delete": False, "exists": d.is_dir() if name != "installed" else True, "elevated": name in CODE_ROOTS})
            return {"path": "", "entries": entries, "can_write": False}
        if parts == ["installed"]:
            return {"path": "installed", "can_write": False, "entries": [
                {"name": n, "type": "dir", "size": None, "modified": self._iso(d.stat().st_mtime), "editable": False, "can_delete": False}
                for n, d in sorted(self.installed_apps().items())]}
        d = self.resolve(rel)
        if not d.is_dir():
            raise ValidationError("That is not a folder")
        entries = []
        with os.scandir(d) as it:
            for e in sorted(it, key=lambda x: (not x.is_dir(follow_symlinks=False), x.name.lower())):
                if _is_secret(e.name) or e.name == "__pycache__" or e.name.endswith((".pyc", ".pyo")):
                    continue                                                    # not even listed
                st = e.stat(follow_symlinks=False)
                link = stat.S_ISLNK(st.st_mode)
                isdir = stat.S_ISDIR(st.st_mode)
                child = "/".join([*parts, e.name])
                entries.append({"name": e.name, "type": "link" if link else "dir" if isdir else "file", "size": None if isdir or link else st.st_size,
                                "modified": self._iso(st.st_mtime), "editable": (not isdir and not link and self.can(child, "edit") and self._is_text_name(e.name) and st.st_size <= MAX_EDIT_BYTES),
                                "can_delete": not link and self.can(child, "delete")})
        return {"path": "/".join(parts), "entries": entries, "can_write": self.can("/".join(parts), "edit"), "needs_unlock": parts[0] in CODE_ROOTS}

    @staticmethod
    def _is_text_name(name: str) -> bool:
        return Path(name).suffix.lower() in TEXT_SUFFIXES

    def read_text(self, rel: str) -> dict:
        p = self.resolve(rel)
        if not p.is_file():
            raise ValidationError("That is not a file")
        size = p.stat().st_size
        if size > MAX_EDIT_BYTES:
            raise ValidationError(f"Too large to open here ({size // 1024} KB; the limit is {MAX_EDIT_BYTES // 1024} KB). Download it instead.")
        data = p.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValidationError("This is not a text file. Download it instead.") from None
        if "\x00" in text:
            raise ValidationError("This is not a text file. Download it instead.")
        return {"path": "/".join(self.parts(rel)), "content": text, "modified": p.stat().st_mtime_ns, "editable": self.can(rel, "edit") and self._is_text_name(p.name),
                "needs_unlock": self.parts(rel)[0] in CODE_ROOTS}

    def file_for_download(self, rel: str) -> Path:
        p = self.resolve(rel)
        if not p.is_file():
            raise ValidationError("That is not a file")
        return p

    # ---- changing --------------------------------------------------------------------------------------------------------------------------
    def _atomic_write(self, target: Path, data: bytes):
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".velora-upload-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---- keeping the old version, and refusing code that would not load -------------------------------------------------------------------
    @staticmethod
    def check_syntax(name: str, data: bytes):
        suffix = Path(name).suffix.lower()
        if suffix not in (".py", ".json"):
            return
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValidationError(f"{name} is not valid UTF-8 text") from None
        if suffix == ".json":
            try:
                json.loads(text)
            except ValueError as e:
                raise ValidationError(f"{name} is not valid JSON, so it was not saved: {e}") from None
        else:
            try:
                compile(text, name, "exec", dont_inherit=True)
            except SyntaxError as e:
                raise ValidationError(f"{name} has a Python error, so it was not saved: line {e.lineno}: {e.msg}") from None

    @property
    def history_dir(self) -> Path:
        return self.root / "backups" / "file-history"

    @staticmethod
    def _slug(rel: str) -> str:
        return rel.replace("%", "%25").replace("/", "%2F")

    def snapshot(self, rel: str, p: Path):
        """Keep what is about to be replaced or removed (code roots and apps only; the newest 25 versions per file)."""
        parts = self.parts(rel)
        if parts[0] not in HISTORY_ROOTS or not p.is_file():
            return
        d = self.history_dir
        d.mkdir(parents=True, exist_ok=True)
        slug = self._slug("/".join(parts))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        shutil.copy2(p, d / f"{stamp}~{slug}")
        old = sorted(d.glob(f"*~{slug}"))
        for extra in old[:-HISTORY_KEEP]:
            extra.unlink(missing_ok=True)

    def history(self, rel: str) -> list[dict]:
        parts = self.parts(rel)
        slug = self._slug("/".join(parts))
        d = self.history_dir
        if not d.is_dir():
            return []
        out = []
        for f in sorted(d.glob(f"*~{slug}"), reverse=True):
            out.append({"version": f.name.split("~", 1)[0], "size": f.stat().st_size, "modified": self._iso(f.stat().st_mtime)})
        return out

    def restore(self, rel: str, version: str) -> dict:
        self._require(rel, "edit")
        if not re.fullmatch(r"\d{8}T\d{12}Z", str(version or "")):
            raise ValidationError("Unknown version")
        src = self.history_dir / f"{version}~{self._slug('/'.join(self.parts(rel)))}"
        if not src.is_file():
            raise ValidationError("That version is no longer kept")
        data = src.read_bytes()
        self.check_syntax(self.parts(rel)[-1], data)
        target = self.resolve(rel)
        self.snapshot(rel, target)
        self._atomic_write(target, data)
        return {"path": "/".join(self.parts(rel)), "size": len(data), "modified": target.stat().st_mtime_ns}

    def copy(self, rel: str, new_rel: str) -> dict:
        """Copy a file to a new name (anywhere you may create files); an existing name is never replaced."""
        src = self.resolve(rel)
        if not src.is_file():
            raise ValidationError("Only files can be copied")
        parts = self.parts(new_rel)
        if len(parts) < 2:
            raise ValidationError("Choose a folder and a name for the copy")
        _clean_name(parts[-1])
        self._require(new_rel, "edit")
        dst = self.resolve(new_rel, must_exist=False)
        if dst.exists():
            raise ValidationError("A file or folder with that name already exists")
        data = src.read_bytes()
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValidationError("Too large to copy here")
        self.check_syntax(parts[-1], data)
        self._atomic_write(dst, data)
        return {"path": "/".join(parts)}

    def write_text(self, rel: str, content: str, expected_modified: int | None = None) -> dict:
        self._require(rel, "edit")
        if not isinstance(content, str):
            raise ValidationError("content must be text")
        data = content.encode("utf-8")
        if len(data) > MAX_EDIT_BYTES:
            raise ValidationError(f"Too large to save here (limit {MAX_EDIT_BYTES // 1024} KB)")
        if "\x00" in content:
            raise ValidationError("Text cannot contain NUL characters")
        p = self.resolve(rel)
        if not p.is_file() or not self._is_text_name(p.name):
            raise ValidationError("Only existing text files can be edited")
        if expected_modified is not None and p.stat().st_mtime_ns != int(expected_modified):
            raise ValidationError("This file changed since you opened it. Reload it, then apply your edit again.")
        self.check_syntax(p.name, data)
        self.snapshot(rel, p)
        self._atomic_write(p, data)
        return {"path": "/".join(self.parts(rel)), "modified": p.stat().st_mtime_ns, "size": len(data), "restart_required": self.parts(rel)[0] in CODE_ROOTS}

    def new_file(self, rel: str, content: str = "") -> dict:
        parts = self.parts(rel)
        if len(parts) < 2:
            raise ValidationError("Choose a folder first")
        _clean_name(parts[-1])
        self._require(rel, "edit")
        p = self.resolve(rel, must_exist=False)
        if p.exists():
            raise ValidationError("A file or folder with that name already exists")
        if not self._is_text_name(parts[-1]):
            raise ValidationError("New files here are text files (.txt, .py, .json, .md ...). Use Upload for other types.")
        self.check_syntax(parts[-1], str(content).encode("utf-8"))
        self._atomic_write(p, str(content).encode("utf-8"))
        return {"path": "/".join(parts), "restart_required": parts[0] in CODE_ROOTS}

    def upload(self, folder: str, filename: str, data: bytes, overwrite: bool = False) -> dict:
        if not self.parts(folder):
            raise ValidationError("Choose a folder first")
        self._require(folder, "edit")
        name = _clean_name(filename)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValidationError(f"Too large (limit {MAX_UPLOAD_BYTES // 1024 // 1024} MB)")
        d = self.resolve(folder)
        if not d.is_dir():
            raise ValidationError("That is not a folder")
        target = self.resolve("/".join([*self.parts(folder), name]), must_exist=False)
        if target.exists() and not overwrite:
            raise ValidationError(f"{name} already exists. Tick 'replace' to overwrite it.")
        if target.is_dir():
            raise ValidationError("A folder with that name already exists")
        self.check_syntax(name, data)
        self.snapshot("/".join([*self.parts(folder), name]), target)
        self._atomic_write(target, data)
        return {"path": "/".join([*self.parts(folder), name]), "size": len(data), "restart_required": self.parts(folder)[0] in CODE_ROOTS}

    def mkdir(self, rel: str) -> dict:
        parts = self.parts(rel)
        if len(parts) < 2:
            raise ValidationError("Create folders inside apps/ or files/")
        _clean_name(parts[-1])
        self._require(rel, "edit")
        p = self.resolve(rel, must_exist=False)
        if p.exists():
            raise ValidationError("A file or folder with that name already exists")
        p.mkdir()
        return {"path": "/".join(parts)}

    def rename(self, rel: str, new_name: str) -> dict:
        parts = self.parts(rel)
        if len(parts) < 2:
            raise ValidationError("The top-level folders cannot be renamed")
        if parts[0] in CODE_ROOTS:
            raise PermissionDenied("Framework and installed-app files cannot be renamed; copy the file instead")
        self._require(rel, "edit")
        name = _clean_name(new_name)
        src = self.resolve(rel)
        dst = self.resolve("/".join([*parts[:-1], name]), must_exist=False)
        if dst.exists():
            raise ValidationError("A file or folder with that name already exists")
        src.rename(dst)
        return {"path": "/".join([*parts[:-1], name])}

    def delete(self, rel: str, recursive: bool = False) -> dict:
        parts = self.parts(rel)
        if len(parts) < 2:
            raise PermissionDenied("The top-level folders cannot be deleted")
        self._require(rel, "delete")
        p = self.resolve(rel)
        self.snapshot(rel, p)
        if p.is_dir():
            if any(p.iterdir()):
                if not recursive:
                    raise ValidationError("The folder is not empty. Confirm to delete it with everything in it.")
                self._remove_tree(p)
            else:
                p.rmdir()
        else:
            p.unlink()
        return {"deleted": "/".join(parts)}

    def _remove_tree(self, d: Path):
        for e in os.scandir(d):
            if e.is_dir(follow_symlinks=False):
                self._remove_tree(Path(e.path))
            else:
                os.unlink(e.path)                                               # a symbolic link is removed as a link, never followed
        d.rmdir()
