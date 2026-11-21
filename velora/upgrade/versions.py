"""Version handling for the framework and apps."""
from __future__ import annotations

import importlib

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


def parse(v) -> Version:
    try:
        return Version(str(v))
    except InvalidVersion:
        return Version("0")


def code_version() -> str:
    import velora
    return velora.__version__


def minor_key(v) -> tuple[int, int]:
    p = parse(v)
    return (p.major, p.minor)


def app_version(app: str) -> str:
    try:
        return str(getattr(importlib.import_module(app), "__version__", "0.0.0"))
    except ImportError:
        return "?"


def satisfies(spec: str | None, version: str) -> bool:
    if not spec:
        return True
    try:
        return SpecifierSet(spec).contains(parse(version), prereleases=True)
    except InvalidSpecifier:
        return False


def compare(a, b) -> int:
    pa, pb = parse(a), parse(b)
    return (pa > pb) - (pa < pb)
