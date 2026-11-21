"""Optional capabilities: heavy or specialised packages that Velora can use but does not force on everyone.

    pip install "velora[pdf]"            # or: velora deps install pdf
    pip install "velora[all]"            # everything below (except Oracle)

Why they are extras and not core dependencies: a plain install must stay small and always succeed. `prophet` needs a Stan toolchain, numpy/pandas/scikit-learn are
hundreds of MB, and not every business needs forecasting. Code that needs one calls `require("pdf", feature="Printing")` and a missing package produces ONE clear
message with the exact command - never a bare ImportError. Apps declare what they need with `required_packages = [...]` in hooks.py; install/upgrade check it first.
"""
from __future__ import annotations

import importlib.metadata as md
import subprocess
import sys
from dataclasses import dataclass

from packaging.requirements import InvalidRequirement, Requirement

from .exceptions import VeloraError


class MissingDependency(VeloraError):
    status_code = 501


class DependencyError(VeloraError):
    status_code = 500


@dataclass(frozen=True)
class Extra:
    name: str
    description: str
    requirements: tuple[str, ...]


EXTRAS: dict[str, Extra] = {e.name: e for e in (
    Extra("postgres", "PostgreSQL driver (recommended for real use)", ("psycopg[binary]>=3.1",)),
    Extra("data", "numpy, pandas, dates and time zones for analysis and reports", ("numpy>=1.26", "pandas>=2.1", "python-dateutil>=2.8", "pytz>=2023.3")),
    Extra("pdf", "PDF documents, QR codes and images (print formats, e-invoice QR)", ("reportlab>=4.0", "qrcode[pil]>=7.4", "pillow>=10.0")),
    Extra("ml", "machine learning and statistics (scikit-learn, statsmodels)", ("scikit-learn>=1.4", "statsmodels>=0.14", "numpy>=1.26", "pandas>=2.1")),
    Extra("forecast", "time-series forecasting with Prophet (heavy: needs a Stan toolchain)", ("prophet>=1.1", "statsmodels>=0.14", "pandas>=2.1")),
    Extra("markets", "market data via yfinance (unofficial Yahoo endpoints: not for anything critical)", ("yfinance>=0.2.40",)),
    Extra("sftp", "SFTP/SSH for bank files and remote servers (paramiko)", ("paramiko>=3.4",)),
    Extra("security", "bcrypt, for verifying legacy password hashes", ("bcrypt>=4.1",)),
)}
EXTRAS["all"] = Extra("all", "everything above", tuple(dict.fromkeys(r for e in list(EXTRAS.values()) for r in e.requirements)))

# names people commonly type that do not mean what they think
ALIASES = {"sklearn": "scikit-learn (the 'ml' extra). The 'sklearn' package on PyPI is a deliberately broken placeholder", "PIL": "pillow (the 'pdf' extra)"}


def _name(req: str) -> str:
    return Requirement(req).name


def installed_version(dist: str) -> str | None:
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        return None


def check_requirement(req: str) -> dict:
    r = Requirement(req)
    have = installed_version(r.name)
    ok = have is not None and (not r.specifier or r.specifier.contains(have, prereleases=True))
    return {"requirement": req, "name": r.name, "installed": have, "ok": ok}


def status(extra: str) -> dict:
    if extra not in EXTRAS:
        raise DependencyError(f"Unknown extra {extra!r}. Available: {', '.join(EXTRAS)}")
    rows = [check_requirement(r) for r in EXTRAS[extra].requirements]
    return {"name": extra, "description": EXTRAS[extra].description, "requirements": rows, "complete": all(r["ok"] for r in rows),
            "installed": sum(r["ok"] for r in rows), "total": len(rows)}


def which_extra(dist: str) -> str | None:
    d = dist.lower().replace("_", "-")
    for e in EXTRAS.values():
        if e.name != "all" and any(_name(r).lower() == d for r in e.requirements):
            return e.name
    return None


def require(*dists: str, feature: str = "This feature") -> None:
    """Raise one clear error (with the exact command) if a needed package is missing."""
    missing = [d for d in dists if installed_version(d) is None]
    if not missing:
        return
    extras = sorted({e for d in missing if (e := which_extra(d))})
    hint = f'pip install "velora[{",".join(extras)}]"   (or: velora deps install {" ".join(extras)})' if extras else f"pip install {' '.join(missing)}"
    raise MissingDependency(f"{feature} needs {', '.join(missing)}, which is not installed. Install it with:  {hint}", details={"missing": missing, "extras": extras})


def check_packages(requirements: list[str] | tuple[str, ...]) -> list[str]:
    """Problems with a list of requirement strings (an app's `required_packages`); empty means all good."""
    problems = []
    for req in requirements or []:
        try:
            c = check_requirement(req)
        except InvalidRequirement:
            problems.append(f"{req!r} is not a valid requirement")
            continue
        if c["installed"] is None:
            problems.append(f"{req} is not installed")
        elif not c["ok"]:
            problems.append(f"{req} is required but {c['installed']} is installed")
    return problems


def requirements_for(names: list[str]) -> list[str]:
    out: list[str] = []
    for n in names:
        if n in ALIASES:
            raise DependencyError(f"{n!r}: use {ALIASES[n]}")
        if n not in EXTRAS:
            raise DependencyError(f"Unknown extra {n!r}. Available: {', '.join(EXTRAS)}")
        out += EXTRAS[n].requirements
    return list(dict.fromkeys(out))


def install(requirements: list[str], *, upgrade: bool = False, dry_run: bool = False, run=subprocess.run) -> dict:
    """pip-install exact requirement strings into THIS Python environment. Only strings that parse as requirements are accepted (no shell, no options)."""
    for r in requirements:
        try:
            Requirement(r)
        except InvalidRequirement:
            raise DependencyError(f"{r!r} is not a valid requirement") from None
        if r.strip().startswith("-"):
            raise DependencyError(f"{r!r} looks like a pip option, not a requirement")
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *(["--upgrade"] if upgrade else []), *requirements]
    if dry_run or not requirements:
        return {"command": cmd, "returncode": 0, "output": "", "ran": False}
    proc = run(cmd, capture_output=True, text=True, timeout=3600)
    tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-8:])
    if proc.returncode:
        hint = ("\nThis Python is managed by your operating system. Install Velora in a virtual environment (python3 -m venv ...), as the server installer does."
                if "externally-managed-environment" in (proc.stderr or "") else "")
        raise DependencyError(f"pip failed (exit {proc.returncode}):\n{tail}{hint}", details={"command": cmd})
    return {"command": cmd, "returncode": 0, "output": tail, "ran": True}
