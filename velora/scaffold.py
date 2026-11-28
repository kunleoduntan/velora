"""Templates for `velora new-app` and `velora new-doctype`."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .meta.registry import pascal
from .workspace import APP_NAME_RE, WorkspaceError

DOCTYPE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ]{0,60}$")


def snake(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def new_app(apps_dir: Path, name: str, module: str | None = None, title: str | None = None) -> Path:
    if not APP_NAME_RE.match(name):
        raise WorkspaceError(f"Invalid app name {name!r}: use lowercase letters, digits and underscores, starting with a letter")
    root = apps_dir / name
    if root.exists():
        raise WorkspaceError(f"App {name} already exists at {root}")
    module = module or name.replace("_", " ").title()
    pkg = root / name
    mod = pkg / snake(module)
    (mod / "doctype").mkdir(parents=True)
    (root / "pyproject.toml").write_text(f'''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "0.0.1"
description = "{title or module} - a Velora app"
dependencies = ["velora"]

[tool.setuptools.packages.find]
include = ["{name}*"]

[tool.setuptools.package-data]
"*" = ["*.json", "*.js", "patches.txt"]
''')
    (root / "README.md").write_text(f"# {title or module}\n\nA Velora app. Install on a site: `velora --site <site> install-app {name}`\n")
    (pkg / "__init__.py").write_text('__version__ = "0.0.1"\n')
    (pkg / "patches.txt").write_text("# Data patches: one dotted module path per line, each defining execute(). They run once per database during `velora upgrade`.\n[pre_model_sync]\n\n[post_model_sync]\n")
    (pkg / "hooks.py").write_text(f'''app_name = "{name}"
app_title = "{title or module}"
app_description = ""

# Apps that must be installed before this one, e.g. ["accounting"]
required_apps = []

# Which Velora releases this app works with (checked on install and upgrade), e.g. ">=0.8,<0.9"
required_velora = ""

# Run in the site's context right after install / before uninstall, e.g. "{name}.setup.after_install"
before_install = None
after_install = None
before_uninstall = None
after_uninstall = None
before_migrate = None
after_migrate = None

# Browser assets shipped inside this app package (relative to the Python package).
# JavaScript, ES modules and CSS only; paths are served only while this app is installed.
frontend_assets = []

# Extend other apps' DocTypes without editing them.
doc_events = {{}}
scheduler_events = {{}}
job_handlers = {{}}
''')
    (mod / "__init__.py").write_text("")
    (mod / "doctype" / "__init__.py").write_text("")
    return root


def _find_module_dir(app_root: Path, app: str, module: str | None) -> tuple[Path, str]:
    pkg = app_root / app
    if not pkg.is_dir():
        raise WorkspaceError(f"{pkg} is not an app package")
    if module:
        d = pkg / snake(module)
        return d, module
    mods = [d for d in pkg.iterdir() if (d / "doctype").is_dir()]
    if len(mods) == 1:
        return mods[0], mods[0].name.replace("_", " ").title()
    raise WorkspaceError("This app has " + ("several modules" if mods else "no module yet") + "; pass --module <name>")


def new_doctype(app_root: Path, app: str, name: str, module: str | None = None, submittable: bool = False,
                child: bool = False) -> Path:
    if not DOCTYPE_NAME_RE.match(name):
        raise WorkspaceError(f"Invalid DocType name {name!r} (letters, digits and spaces)")
    if submittable and child:
        raise WorkspaceError("A child table cannot be submittable")
    mod_dir, module_title = _find_module_dir(app_root, app, module)
    folder = snake(name)
    d = mod_dir / "doctype" / folder
    if d.exists():
        raise WorkspaceError(f"DocType {name} already exists at {d}")
    (mod_dir / "doctype").mkdir(parents=True, exist_ok=True)
    (mod_dir / "__init__.py").touch()
    (mod_dir / "doctype" / "__init__.py").touch()
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    spec: dict = {"name": name, "module": module_title}
    if child:
        spec["istable"] = True
        spec["fields"] = [{"fieldname": "description", "fieldtype": "Data", "in_list_view": True}]
    else:
        spec["autoname"] = f"series:{''.join(w[0] for w in name.split()).upper()[:4] or 'DOC'}-.####"
        if submittable:
            spec["is_submittable"] = True
        spec["track_changes"] = True
        spec["fields"] = [{"fieldname": "title", "label": "Title", "fieldtype": "Data", "required": True, "in_list_view": True}]
        perm = {"role": "System Manager", "read": True, "write": True, "create": True, "delete": True, "export": True, "import": True, "report": True, "amend": True, "share": True, "print": True, "email": True}
        if submittable:
            perm.update(submit=True, cancel=True)
        spec["permissions"] = [perm]
    (d / f"{folder}.json").write_text(json.dumps(spec, indent=2) + "\n")
    if not child:
        (d / f"{folder}.py").write_text(f'''from velora import Document, throw  # noqa: F401


class {pascal(name)}(Document):
    def validate(self):
        pass
''')
        (d / f"{folder}.js").write_text(f'''velora.ui.form.on("{name}", {{
  refresh(frm) {{}},
}});
''')
        (d / f"{folder}_list.js").write_text(f'''velora.listview_settings["{name}"] = {{
  add_fields: [],
}};
''')
    return d
