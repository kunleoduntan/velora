"""Publish an app (or the Velora project itself) to Git from the Desk.

A *publish profile* ties together the four things that must never be mixed up:  the project (an app on this server, or an
uploaded copy of a project folder), the company it belongs to, the repository, and the branch.  The access token is kept
encrypted in the control plane's secret store and is never returned or written to disk (git receives it through a short-lived
askpass helper), so it cannot appear in a URL, a log, `git remote -v` or the browser.

Everything here runs ordinary `git` without a shell.  There is no force-push: if the remote has commits this copy does not,
the push is refused with an explanation instead of overwriting them.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .exceptions import DoesNotExistError, ValidationError
from .filemanager import _is_secret

PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
HTTPS_REPO_RE = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?/[A-Za-z0-9._~-]+(/[A-Za-z0-9._~-]+)+?(\.git)?/?$")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode", "build"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".log")
MAX_ZIP_BYTES = 200 * 1024 * 1024
MAX_UNPACKED_BYTES = 600 * 1024 * 1024
MAX_FILES = 30000
GIT_TIMEOUT = 300
DEFAULT_GITIGNORE = "__pycache__/\n*.pyc\nnode_modules/\n.venv/\nvenv/\n.env\n.env.*\n*.key\n*.pem\n.pytest_cache/\n"

ALLOW_LOCAL_REMOTES = False        # tests only: lets a profile point at a local bare repository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git_available() -> bool:
    return shutil.which("git") is not None


class Publisher:
    def __init__(self, plane):
        self.plane = plane
        self.ws = plane.ws
        self.file = self.ws.root / "platform" / "publish_profiles.json"
        self.stage_root = self.ws.root / "publish"

    # ------------------------------------------------------------------------------------------------------ profiles
    def _load(self) -> dict:
        try:
            return json.loads(self.file.read_text()) if self.file.exists() else {}
        except ValueError:
            raise ValidationError("The publish profiles file is damaged; fix or remove platform/publish_profiles.json") from None

    def _save(self, data: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        os.chmod(tmp, 0o600)
        tmp.replace(self.file)

    def _public(self, p: dict) -> dict:
        co = self.plane.registry.get_company(p["company_id"])
        return {**{k: v for k, v in p.items() if k != "token_ref"}, "has_token": bool(p.get("token_ref")),
                "company_name": co["name"] if co else "(company no longer exists)", "workdir": self._workdir_label(p)}

    def _workdir_label(self, p: dict) -> str:
        return f"apps/{p['app']}" if p["source"] == "app" else f"publish/{p['id']}"

    def list(self) -> list[dict]:
        return [self._public(p) for p in self._load().values()]

    def get(self, pid: str) -> dict:
        p = self._load().get(pid)
        if not p:
            raise DoesNotExistError(f"No publish profile {pid!r}")
        return p

    def apps_here(self) -> list[str]:
        return [a for a in self.ws.apps() if (self.ws.apps_dir / a).is_dir()]

    def save(self, body: dict, actor: str) -> dict:
        pid = str(body.get("id") or "").strip().lower()
        if not PROFILE_ID_RE.match(pid):
            raise ValidationError("Profile name: lower-case letters, digits and dashes, up to 40 characters")
        source = str(body.get("source") or "")
        if source not in ("app", "upload"):
            raise ValidationError("Choose where the code comes from: an app on this server, or an uploaded project folder")
        company_id = str(body.get("company_id") or "")
        if not company_id or not self.plane.registry.get_company(company_id):
            raise ValidationError("Choose the company this belongs to")
        repo = str(body.get("repo_url") or "").strip()
        if not (HTTPS_REPO_RE.match(repo) or (ALLOW_LOCAL_REMOTES and Path(repo).is_absolute())):
            raise ValidationError("Repository address must look like https://github.com/owner/repo (no password or token in the address; use the token field)")
        branch = str(body.get("branch") or "main").strip()
        if not BRANCH_RE.match(branch) or ".." in branch or branch.endswith(("/", ".lock")):
            raise ValidationError("That branch name is not valid")
        app = None
        if source == "app":
            app = str(body.get("app") or "")
            if app not in self.apps_here():
                raise ValidationError(f"There is no app named {app!r} on this server")
        data = self._load()
        old = data.get(pid, {})
        if old and (old.get("source") != source or old.get("app") != app or old.get("company_id") != company_id):
            # changing what a profile points at is how mix-ups happen: make it a new profile instead
            raise ValidationError("A profile's project and company cannot be changed. Create a new profile (or delete this one) so nothing is pushed to the wrong place.")
        token = str(body.get("token") or "").strip()
        if token and not re.fullmatch(r"[\x21-\x7e]{8,300}", token):
            raise ValidationError("That does not look like an access token")
        ref = old.get("token_ref")
        if token:
            ref = self.plane.secrets.put(token)
        data[pid] = {"id": pid, "label": str(body.get("label") or pid)[:80], "source": source, "app": app, "company_id": company_id, "repo_url": repo,
                     "branch": branch, "author_name": str(body.get("author_name") or "Velora")[:80], "author_email": str(body.get("author_email") or "velora@localhost")[:120],
                     "token_ref": ref, "last_push": old.get("last_push"), "created": old.get("created") or _now()}
        self._save(data)
        self.plane.audit("publish.save", actor=actor, subject=pid, detail={"company": company_id, "repo": repo, "branch": branch})
        return self._public(data[pid])

    def delete(self, pid: str, actor: str) -> None:
        data = self._load()
        if pid not in data:
            raise DoesNotExistError(f"No publish profile {pid!r}")
        del data[pid]
        self._save(data)
        shutil.rmtree(self.stage_root / pid, ignore_errors=True)         # an app's own folder is never touched
        self.plane.audit("publish.delete", actor=actor, subject=pid, detail={})

    # ------------------------------------------------------------------------------------------------------ the work folder
    def workdir(self, p: dict) -> Path:
        if p["source"] == "app":
            d = self.ws.apps_dir / p["app"]
            if not d.is_dir():
                raise ValidationError(f"The app folder apps/{p['app']} no longer exists")
            return d
        return self.stage_root / p["id"]

    def check_company(self, p: dict) -> dict:
        """The guard against pushing one company's app under another: the app must be installed in the company the profile names."""
        co = self.plane.registry.get_company(p["company_id"])
        if co is None:
            raise ValidationError("The company this profile belongs to no longer exists")
        if p["source"] != "app":
            return {"company": co["name"], "checked": False, "note": "An uploaded folder cannot be checked against a company's installed apps."}
        try:
            installed = list(self.plane.router.site_for(co).installed_apps())
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"Could not read {co['name']}'s installed apps: {exc}") from None
        if p["app"] not in installed:
            raise ValidationError(f"{p['app']} is not installed in {co['name']}. Install it there first, or make a profile for the company that really uses it.")
        return {"company": co["name"], "checked": True, "note": f"{p['app']} is installed in {co['name']}."}

    def upload_zip(self, pid: str, data: bytes, actor: str) -> dict:
        p = self.get(pid)
        if p["source"] != "upload":
            raise ValidationError("This profile publishes an app already on the server; there is nothing to upload")
        if len(data) > MAX_ZIP_BYTES:
            raise ValidationError("That zip is larger than 200 MB")
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ValidationError("That is not a zip file. Right-click the project folder and choose Compress / Send to > Compressed folder.") from None
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
            raise ValidationError("That zip holds too many or too large files for a project upload")
        entries = []
        for i in infos:
            name = i.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or (len(parts) and re.match(r"^[A-Za-z]:$", parts[0])):
                raise ValidationError(f"The zip contains an unsafe path ({name!r}); nothing was changed")
            if stat.S_ISLNK(i.external_attr >> 16):
                raise ValidationError(f"The zip contains a symbolic link ({name!r}); nothing was changed")
            entries.append((i, parts))
        top = {parts[0] for _, parts in entries if len(parts) > 1}
        strip = 1 if entries and len(top) == 1 and all(len(parts) > 1 for _, parts in entries) else 0     # a single wrapper folder is removed
        dest = self.stage_root / pid
        dest.mkdir(parents=True, exist_ok=True)
        # build the new tree beside the old one, then swap, keeping .git so history survives
        new = Path(tempfile.mkdtemp(prefix=".new-", dir=self.stage_root))
        written, skipped = 0, []
        try:
            for i, parts in entries:
                rel = parts[strip:]
                if not rel:
                    continue
                if any(x in SKIP_DIRS for x in rel[:-1]) or rel[-1].endswith(SKIP_SUFFIXES) or _is_secret(rel[-1]) or rel[-1] == ".DS_Store":
                    skipped.append("/".join(rel)); continue
                target = new.joinpath(*rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(i) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                written += 1
            if not written:
                raise ValidationError("The zip had no usable files in it")
            for child in dest.iterdir():
                if child.name != ".git":
                    shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
            for child in new.iterdir():
                shutil.move(str(child), str(dest / child.name))
        finally:
            shutil.rmtree(new, ignore_errors=True)
        self.plane.audit("publish.upload", actor=actor, subject=pid, detail={"files": written, "skipped": len(skipped)})
        return {"files": written, "skipped": skipped[:20], "skipped_count": len(skipped), "stripped_top_folder": bool(strip)}

    # ------------------------------------------------------------------------------------------------------ git
    def _git(self, cwd: Path, *args: str, token: str | None = None, p: dict | None = None, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
        if not git_available():
            raise ValidationError("git is not installed on this server. Install it once with: sudo apt install git")
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT")}
        env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
        env.setdefault("HOME", str(self.ws.root))
        helper = None
        if token:
            fd, helper = tempfile.mkstemp(prefix="velora-askpass-")
            with os.fdopen(fd, "w") as f:
                f.write('#!/bin/sh\ncase "$1" in *sername*) echo "$VELORA_GIT_USER";; *) echo "$VELORA_GIT_TOKEN";; esac\n')
            os.chmod(helper, 0o700)
            env.update(GIT_ASKPASS=helper, VELORA_GIT_TOKEN=token, VELORA_GIT_USER="x-access-token")
        ident = ["-c", f"user.name={(p or {}).get('author_name', 'Velora')}", "-c", f"user.email={(p or {}).get('author_email', 'velora@localhost')}",
                 "-c", "credential.helper=", "-c", "safe.directory=*", "-c", "core.quotepath=off"]
        try:
            r = subprocess.run(["git", *ident, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, shell=False)
        except subprocess.TimeoutExpired:
            raise ValidationError("git took too long and was stopped (the repository or network may be unreachable)") from None
        finally:
            if helper:
                try:
                    os.unlink(helper)
                except OSError:
                    pass
        if token:
            r.stdout, r.stderr = r.stdout.replace(token, "***"), r.stderr.replace(token, "***")
        return r

    def _token(self, p: dict) -> str | None:
        return self.plane.secrets.get(p["token_ref"]) if p.get("token_ref") else None

    def _ensure_repo(self, p: dict, d: Path) -> None:
        if not (d / ".git").exists():
            r = self._git(d, "init", "-b", p["branch"], p=p)
            if r.returncode:
                raise ValidationError("git init failed: " + r.stderr.strip()[:300])
        if not (d / ".gitignore").exists():
            (d / ".gitignore").write_text(DEFAULT_GITIGNORE)
        have = self._git(d, "remote", "get-url", "origin", p=p)
        if have.returncode:
            self._git(d, "remote", "add", "origin", p["repo_url"], p=p)
        elif have.stdout.strip() != p["repo_url"]:
            self._git(d, "remote", "set-url", "origin", p["repo_url"], p=p)

    def status(self, pid: str) -> dict:
        p = self.get(pid)
        d = self.workdir(p)
        out = {"profile": self._public(p), "git": git_available(), "ready": d.is_dir() and any(d.iterdir()) if d.is_dir() else False, "changes": [], "last_commit": None}
        if not out["git"] or not (d / ".git").exists():
            return out
        r = self._git(d, "status", "--short", p=p)
        out["changes"] = [l for l in r.stdout.splitlines()][:60]
        r = self._git(d, "log", "-1", "--format=%h %s", p=p)
        out["last_commit"] = r.stdout.strip() or None
        return out

    def test_connection(self, pid: str) -> dict:
        p = self.get(pid)
        if not p.get("token_ref") and p["repo_url"].startswith("https://"):
            raise ValidationError("Add the access token first")
        r = self._git(self.ws.root, "ls-remote", "--heads", p["repo_url"], token=self._token(p), p=p, timeout=60)
        if r.returncode:
            raise ValidationError(self._explain(r.stderr))
        return {"ok": True, "branches": [l.split("refs/heads/")[-1] for l in r.stdout.splitlines()][:20]}

    @staticmethod
    def _explain(stderr: str) -> str:
        e = stderr.strip()
        low = e.lower()
        if "authentication failed" in low or "invalid username or password" in low or "could not read username" in low:
            return "GitHub refused the token. Check it is current, and that it can write to this repository (classic token: `repo`; fine-grained: Contents = Read and write)."
        if "repository not found" in low or "not found" in low:
            return "The repository was not found. Check the address, and that the token's owner can see it."
        if "non-fast-forward" in low or "fetch first" in low or "rejected" in low:
            return ("The repository already has commits that this copy does not. Nothing was overwritten. Either publish the same project that is already there, or "
                    "push to an empty repository or a new branch name.")
        if "could not resolve host" in low or "unable to access" in low:
            return "The server could not reach the repository host. Check the address and the server's internet access."
        return e[:400] or "git failed"

    def commands(self, pid: str) -> str:
        p = self.get(pid)
        co = self.plane.registry.get_company(p["company_id"])
        return "\n".join([f"# {p['label']}  |  company: {co['name'] if co else p['company_id']}  |  {p['repo_url']} ({p['branch']})",
                          f"git init -b {p['branch']}", "git add -A", "git status --short | head -20", 'git commit -m "Update"',
                          f"git remote add origin {p['repo_url']}", f"git push -u origin {p['branch']}"])

    def push(self, pid: str, message: str, actor: str) -> dict:
        p = self.get(pid)
        message = (message or "").strip()[:300] or f"Update from Velora ({_now()[:10]})"
        guard = self.check_company(p)
        d = self.workdir(p)
        if p["source"] == "upload" and not (d.is_dir() and any(x.name != ".git" for x in d.iterdir())):
            raise ValidationError("Upload the project zip first")
        if p["repo_url"].startswith("https://") and not p.get("token_ref"):
            raise ValidationError("Add the access token to this profile first")
        token = self._token(p)
        self._ensure_repo(p, d)
        cur = self._git(d, "symbolic-ref", "--short", "HEAD", p=p).stdout.strip()
        if cur and cur != p["branch"]:
            c = self._git(d, "checkout", "-B", p["branch"], p=p)
            if c.returncode:
                raise ValidationError("Could not switch to branch " + p["branch"] + ": " + c.stderr.strip()[:200])
        add = self._git(d, "add", "-A", p=p)
        if add.returncode:
            raise ValidationError("git add failed: " + add.stderr.strip()[:300])
        dirty = bool(self._git(d, "status", "--porcelain", p=p).stdout.strip())
        committed = False
        if dirty:
            c = self._git(d, "commit", "-m", message, p=p)
            if c.returncode:
                raise ValidationError("git commit failed: " + (c.stderr or c.stdout).strip()[:300])
            committed = True
        if self._git(d, "rev-parse", "--verify", "HEAD", p=p).returncode:
            raise ValidationError("There is nothing to publish: the project has no files")
        r = self._git(d, "push", "-u", "origin", f"HEAD:refs/heads/{p['branch']}", token=token, p=p)
        if r.returncode:
            raise ValidationError(self._explain(r.stderr))
        sha = self._git(d, "rev-parse", "--short", "HEAD", p=p).stdout.strip()
        up_to_date = "up-to-date" in (r.stderr + r.stdout).lower() and not committed
        data = self._load()
        data[pid]["last_push"] = {"at": _now(), "by": actor, "commit": sha, "message": message if committed else None}
        self._save(data)
        self.plane.audit("publish.push", actor=actor, subject=pid, detail={"company": p["company_id"], "repo": p["repo_url"], "branch": p["branch"], "commit": sha})
        return {"pushed": True, "commit": sha, "new_commit": committed, "already_up_to_date": up_to_date, "company_check": guard,
                "to": f"{p['repo_url']} ({p['branch']})"}
