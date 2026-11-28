#!/usr/bin/env python3
"""Static release preflight for Velora framework and installed applications.

This validates packaging and metadata consistency without connecting to a live
customer database. It deliberately reports configuration candidates instead
of pretending every business constant can be detected automatically.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_toml(path: Path):
    with path.open("rb") as stream:
        return tomllib.load(stream)


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = parser.parse_args()
    checks = []

    def add(code, ok, detail, severity="error"):
        checks.append({"code": code, "status": "pass" if ok else severity, "detail": detail})

    try:
        framework = load_toml(ROOT / "pyproject.toml")
        erp = load_toml(ROOT / "apps/velora_erp/pyproject.toml")
        framework_version = (ROOT / "velora/__init__.py").read_text()
        erp_version = (ROOT / "apps/velora_erp/velora_erp/__init__.py").read_text()
        fv = re.search(r'__version__\s*=\s*["\']([^"\']+)', framework_version)
        ev = re.search(r'__version__\s*=\s*["\']([^"\']+)', erp_version)
        add("FRAMEWORK_VERSION", bool(fv and fv.group(1)), fv.group(1) if fv else "Framework version is missing")
        add("ERP_VERSION", bool(ev and ev.group(1) == erp["project"]["version"]),
            f"module={ev.group(1) if ev else 'missing'}; package={erp['project'].get('version')}")
        requires = erp["project"].get("dependencies", [])
        add("FRAMEWORK_DEPENDENCY", any(x.startswith("velora>=") for x in requires), str(requires))
        pytest_paths = framework.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("pythonpath", [])
        add("ERP_TEST_IMPORT_PATH", "apps/velora_erp" in pytest_paths,
            "pytest pythonpath includes apps/velora_erp" if "apps/velora_erp" in pytest_paths else str(pytest_paths))
    except Exception as exc:
        add("PACKAGE_METADATA", False, f"Unable to read package metadata: {exc}")

    metadata_files = sorted((ROOT / "apps/velora_erp").rglob("*.json"))
    invalid, mismatched = [], []
    for path in metadata_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                invalid.append(str(path.relative_to(ROOT))); continue
            expected = path.parent.name
            declared = data.get("name")
            if declared and declared.lower().replace(" ", "_") != expected.lower():
                mismatched.append(f"{path.relative_to(ROOT)} declares {declared!r}")
        except Exception as exc:
            invalid.append(f"{path.relative_to(ROOT)}: {exc}")
    add("DOCTYPE_JSON_PARSE", not invalid,
        f"{len(metadata_files)} JSON files scanned; {len(invalid)} invalid" + (f": {invalid[:10]}" if invalid else ""))
    add("DOCTYPE_DIRECTORY_NAME", not mismatched,
        f"{len(mismatched)} DocType name/path mismatches" + (f": {mismatched[:10]}" if mismatched else ""), "warning")

    frontend = ROOT / "frontend"
    lockfiles = [p.name for p in (frontend / "package-lock.json", frontend / "pnpm-lock.yaml", frontend / "yarn.lock") if p.exists()]
    add("FRONTEND_LOCKFILE", bool(lockfiles), ", ".join(lockfiles) if lockfiles else "No frontend lockfile found", "warning")
    summary = {"root": str(ROOT), "checks": checks,
               "errors": sum(x["status"] == "error" for x in checks),
               "warnings": sum(x["status"] == "warning" for x in checks)}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for item in checks:
            print(f"[{item['status'].upper()}] {item['code']}: {item['detail']}")
        print(f"Summary: {summary['errors']} error(s), {summary['warnings']} warning(s)")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(run())
