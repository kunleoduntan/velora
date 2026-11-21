"""Optional packages: the extras table, clear errors, `velora deps`, and the install/upgrade preflight for an app's required_packages."""
import json
import sys
try:
    try:
        import tomllib
    except ModuleNotFoundError:          # Python 3.10
        import tomli as tomllib
except ModuleNotFoundError:          # Python 3.10
    import tomli as tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from velora import optional
from velora.cli import main
from velora.workspace import Workspace
from upgrade_helpers import clean_modules, make_app

ROOT = Path(__file__).parent.parent


def test_pyproject_extras_match_the_code_exactly():
    """The extras live in two places (pyproject for pip, optional.py for `velora deps`); they must never drift apart."""
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]
    for name, e in optional.EXTRAS.items():
        assert name in extras, name
        assert sorted(extras[name]) == sorted(e.requirements), name
    assert {n for n in extras if n not in ("dev", "oracle")} == set(optional.EXTRAS)


def test_every_extra_requirement_is_a_valid_pip_requirement_and_sklearn_is_not_among_them():
    for e in optional.EXTRAS.values():
        for r in e.requirements:
            assert optional.check_requirement(r)["name"]
    names = {optional.check_requirement(r)["name"].lower() for e in optional.EXTRAS.values() for r in e.requirements}
    assert "sklearn" not in names and "scikit-learn" in names                                        # the PyPI 'sklearn' is a broken placeholder
    assert {"numpy", "pandas", "python-dateutil", "pytz", "pillow", "qrcode", "reportlab", "bcrypt", "paramiko", "prophet", "yfinance", "statsmodels", "xlsxwriter"} - names == {"xlsxwriter"}  # XlsxWriter is already core


def test_core_dependencies_stay_light():
    core = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    heavy = {"numpy", "pandas", "scikit-learn", "prophet", "statsmodels", "yfinance", "paramiko", "reportlab", "pillow", "bcrypt"}
    assert not [d for d in core if any(d.lower().startswith(h) for h in heavy)], core                    # a plain install must stay small and always succeed


def test_status_reports_what_is_installed_and_what_is_not(monkeypatch):
    fake = {"numpy": "2.0.0", "pandas": "1.0.0"}                                                           # pandas too old for >=2.1
    monkeypatch.setattr(optional, "installed_version", lambda d: fake.get(d))
    st = optional.status("data")
    by = {r["name"]: r for r in st["requirements"]}
    assert by["numpy"]["ok"] and not by["pandas"]["ok"] and by["pandas"]["installed"] == "1.0.0" and not by["pytz"]["ok"] and by["pytz"]["installed"] is None
    assert st["complete"] is False and (st["installed"], st["total"]) == (1, 4)
    with pytest.raises(optional.DependencyError, match="Unknown extra"):
        optional.status("nope")


def test_require_gives_one_clear_message_with_the_exact_command(monkeypatch):
    monkeypatch.setattr(optional, "installed_version", lambda d: None if d in ("reportlab", "qrcode") else "1.0")
    with pytest.raises(optional.MissingDependency) as e:
        optional.require("reportlab", "qrcode", "pillow", feature="Printing invoices")
    msg = str(e.value)
    assert msg.startswith("Printing invoices needs reportlab, qrcode, which is not installed.") and 'pip install "velora[pdf]"' in msg and "velora deps install pdf" in msg
    assert e.value.details == {"missing": ["reportlab", "qrcode"], "extras": ["pdf"]} and e.value.status_code == 501
    optional.require("pillow")                                                                              # nothing missing: silent
    monkeypatch.setattr(optional, "installed_version", lambda d: None)
    with pytest.raises(optional.MissingDependency, match="pip install some-unlisted-package"):
        optional.require("some-unlisted-package", feature="X")


def test_check_packages_for_an_apps_declared_requirements(monkeypatch):
    monkeypatch.setattr(optional, "installed_version", lambda d: {"alpha": "1.0", "beta": "0.5"}.get(d))
    assert optional.check_packages(["alpha>=1.0", "beta"]) == []
    assert optional.check_packages(["alpha>=2"]) == ["alpha>=2 is required but 1.0 is installed"]
    assert optional.check_packages(["gamma"]) == ["gamma is not installed"]
    assert optional.check_packages(["not a requirement!!"])[0].endswith("is not a valid requirement")
    assert optional.check_packages([]) == [] and optional.check_packages(None) == []


def test_requirements_for_names_expands_all_and_refuses_unknowns_and_the_sklearn_trap():
    assert optional.requirements_for(["sftp"]) == ["paramiko>=3.4"]
    assert "scikit-learn>=1.4" in optional.requirements_for(["ml"]) and len(optional.requirements_for(["ml", "forecast"])) == len(set(optional.requirements_for(["ml", "forecast"])))
    allr = optional.requirements_for(["all"])
    assert "prophet>=1.1" in allr and "psycopg[binary]>=3.1" in allr and not any("oracle" in r for r in allr)
    with pytest.raises(optional.DependencyError, match="use scikit-learn"):
        optional.requirements_for(["sklearn"])
    with pytest.raises(optional.DependencyError, match="Unknown extra 'frobnicate'"):
        optional.requirements_for(["frobnicate"])


def test_install_builds_a_safe_pip_command_and_reports_failures_clearly():
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="Successfully installed paramiko-3.4.0", stderr="")
    out = optional.install(["paramiko>=3.4"], run=fake_run)
    assert out["ran"] and calls[0][:5] == [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"] and calls[0][-1] == "paramiko>=3.4" and "--break-system-packages" not in calls[0]
    assert "--upgrade" in optional.install(["a"], upgrade=True, dry_run=True)["command"] and not optional.install(["a"], dry_run=True)["ran"] and len(calls) == 1
    for evil in ("--index-url=http://evil", "x; rm -rf /", "-r /etc/passwd", "a b"):
        with pytest.raises(optional.DependencyError):
            optional.install([evil], run=fake_run)
    assert len(calls) == 1                                                                                  # nothing was run for the bad ones
    boom = lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="error: externally-managed-environment\n")  # noqa: E731
    with pytest.raises(optional.DependencyError, match="virtual environment"):
        optional.install(["x"], run=boom)
    bad = lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="ERROR: No matching distribution found for nope")  # noqa: E731
    with pytest.raises(optional.DependencyError, match="No matching distribution"):
        optional.install(["nope"], run=bad)


def cli(capsys, *argv):
    code = main(list(argv))
    o = capsys.readouterr()
    return code, o.out, o.err


def test_the_deps_command(capsys, monkeypatch):
    code, out, _ = cli(capsys, "deps", "list")
    assert code is None or code == 0
    assert all(name in out for name in optional.EXTRAS) and 'pip install "velora[<extra>]"' in out
    code, _, err = cli(capsys, "deps", "install")
    assert code == 1 and "Name what to install" in err                                                       # nothing named: tell them what to do
    code, out, err = cli(capsys, "deps", "install", "sklearn")
    assert code == 1 and "use scikit-learn" in err
    monkeypatch.setattr(optional, "installed_version", lambda d: None)
    code, out, _ = cli(capsys, "deps", "install", "sftp", "--dry-run")
    assert code in (None, 0) and "Will install:\n  paramiko>=3.4" in out
    monkeypatch.setattr(optional, "installed_version", lambda d: "99.0")
    assert "already installed" in cli(capsys, "deps", "install", "sftp")[1]


@pytest.fixture
def ws_with_app(tmp_path, monkeypatch):
    for k in ("VELORA_MASTER_KEY", "VELORA_WORKSPACE", "VELORA_SITE"):
        monkeypatch.delenv(k, raising=False)
    before_path, before_mods = list(sys.path), set(sys.modules)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws)
    yield ws
    clean_modules(tmp_path, before_path, before_mods)


def declare(ws, *reqs):
    hooks = ws.app_path("shop") / "shop" / "hooks.py"
    hooks.write_text(hooks.read_text() + f"\nrequired_packages = {json.dumps(list(reqs))}\n")
    for m in [m for m in sys.modules if m.startswith("shop")]:
        del sys.modules[m]


def installed_apps_of(ws, site_name):
    from velora import site as site_mod
    site = site_mod.load_site(ws.site_path(site_name))
    with site_mod.use(site):
        return site.installed_apps()


def test_install_app_installs_the_packages_it_needs_by_itself(ws_with_app, capsys, monkeypatch):
    declare(ws_with_app, "definitely_not_installed_pkg>=1.0")
    assert main(["new-site", "t.local"]) == 0
    capsys.readouterr()
    have, calls = {}, []
    monkeypatch.setattr(optional, "installed_version", lambda d: have.get(d))
    monkeypatch.setattr(optional, "install", lambda reqs, **kw: (calls.append(list(reqs)), have.update({"definitely_not_installed_pkg": "1.2"}))[0])    # pip "installs" it
    assert main(["--site", "t.local", "install-app", "shop", "--no-restart"]) == 0
    out = capsys.readouterr().out
    assert calls == [["definitely_not_installed_pkg>=1.0"]] and "Installing shop's Python packages: definitely_not_installed_pkg>=1.0" in out
    assert "shop" in installed_apps_of(ws_with_app, "t.local") and "installed on 1 of 1" in out                       # one command did everything


def test_if_the_packages_cannot_be_installed_nothing_is_changed(ws_with_app, capsys, monkeypatch):
    declare(ws_with_app, "definitely_not_installed_pkg>=1.0")
    assert main(["new-site", "t.local"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(optional, "install", lambda reqs, **kw: (_ for _ in ()).throw(optional.DependencyError("No matching distribution found for definitely_not_installed_pkg")))
    assert main(["--site", "t.local", "install-app", "shop", "--no-restart"]) == 1
    err = capsys.readouterr().err
    assert "Could not install the packages shop needs, so nothing was changed" in err and "No matching distribution" in err
    assert "shop" not in installed_apps_of(ws_with_app, "t.local")


def test_no_deps_refuses_instead_of_installing(ws_with_app, capsys, monkeypatch):
    declare(ws_with_app, "definitely_not_installed_pkg>=1.0")
    assert main(["new-site", "t.local"]) == 0
    capsys.readouterr()
    called = []
    monkeypatch.setattr(optional, "install", lambda *a, **k: called.append(1))
    assert main(["--site", "t.local", "install-app", "shop", "--no-deps", "--no-restart"]) == 1
    assert "shop needs Python packages: definitely_not_installed_pkg>=1.0" in capsys.readouterr().err and not called
    assert "shop" not in installed_apps_of(ws_with_app, "t.local")
    declare(ws_with_app)                                                                                              # an app that declares nothing installs with no pip call at all
    hooks = ws_with_app.app_path("shop") / "shop" / "hooks.py"
    hooks.write_text(hooks.read_text().replace('required_packages = ["definitely_not_installed_pkg>=1.0"]', "required_packages = []"))
    for m in [m for m in sys.modules if m.startswith("shop")]:
        del sys.modules[m]
    assert main(["--site", "t.local", "install-app", "shop", "--no-restart"]) == 0 and not called


def test_deps_check_and_doctor_report_an_apps_missing_packages(ws_with_app, capsys):
    declare(ws_with_app, "definitely_not_installed_pkg>=1.0")
    code, out, _ = cli(capsys, "deps", "check")
    assert code == 1 and "shop: definitely_not_installed_pkg>=1.0 is not installed" in out
    code, out, _ = cli(capsys, "doctor")
    assert code == 1 and "Packages for shop" in out and "velora deps install --app shop" in out and "Optional: pdf" in out
