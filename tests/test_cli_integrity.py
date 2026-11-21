"""The command line must always be buildable and honest. A duplicated argument or a mis-wired action once made EVERY `velora` command crash."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def cli(*args):
    r = subprocess.run([sys.executable, "-m", "velora.cli", *args], capture_output=True, text=True, timeout=60, cwd=ROOT)
    return r.returncode, r.stdout, r.stderr


def commands():
    code, out, err = cli("--help")
    assert code == 0, err[-500:]
    return sorted(set(re.findall(r"^\s{4}([a-z][a-z-]+)\s", out, re.M)))


def test_the_parser_builds_and_every_subcommand_has_working_help():
    cmds = commands()
    assert len(cmds) >= 30 and {"quickstart", "start", "ops", "install-app", "import-data", "doctor"} <= set(cmds)
    broken = [(c, cli(c, "--help")[2][-200:]) for c in cmds if cli(c, "--help")[0] != 0]
    assert broken == []


def test_no_argument_is_declared_twice_on_any_parser():
    """argparse raises on a duplicate option; a duplicated line would otherwise only show at run time, on every command."""
    src = (ROOT / "velora" / "cli.py").read_text()
    seen: dict = {}
    for m in re.finditer(r"^\s*(\w+)\.add_argument\(([^\n]*?)\)\s*(?:;|$)", src, re.M):
        first_opts = tuple(re.findall(r'"(--?[\w-]+)"', m.group(2)))
        for opt in first_opts:
            key = (m.group(1), opt)
            assert key not in seen, f"{m.group(1)}.add_argument declares {opt} twice"
            seen[key] = 1


def test_every_ops_action_is_handled_and_nothing_falls_through_to_a_destructive_default():
    src = (ROOT / "velora" / "cli.py").read_text()
    choices = set(re.findall(r'"([a-z-]+)"', re.search(r'ops\.add_argument\("action", choices=\[(.*?)\]', src, re.S).group(1)))
    a = src.index("def _cmd_ops(args):")
    body = src[a:src.index("\ndef ", a + 5)]
    handled = re.findall(r'args\.action == "([^"]+)"', body)
    assert choices == set(handled), (choices ^ set(handled))
    assert len(handled) == len(set(handled)), "an ops action is handled twice (a copied block)"
    assert 'raise WorkspaceError(f"Unknown ops action' in body                                              # and an unknown one is an error, never `prune`


def test_the_version_is_declared_once_and_reported_truthfully():
    import velora
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    proj = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "version" not in proj["project"] and "version" in proj["project"]["dynamic"]                    # no second copy to drift
    assert proj["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "velora.__version__"}
    assert re.fullmatch(r"\d+\.\d+\.\d+", velora.__version__)
    # The repository also carries VeloraERP's own release notes (numbered separately), so the framework's version
    # must have its own notes file rather than being compared with "the newest file".
    candidates = [ROOT / f"RELEASE-NOTES-v{velora.__version__}.md", ROOT / f"RELEASE_NOTES-v{velora.__version__}.md",
                  ROOT / f"RELEASE-NOTES-v{velora.__version__.rsplit('.', 1)[0]}.md"]
    assert any(p.exists() for p in candidates), "there are no release notes for velora.__version__"
    _, out, _ = cli("--version")
    assert out.strip() == f"velora {velora.__version__}"


def test_no_http_route_is_registered_twice():
    """A route installer called twice (a copied line) registers every route again: the second is silently ignored and OpenAPI reports duplicate operation IDs."""
    import collections
    from velora.api import create_app
    seen = collections.defaultdict(list)
    for r in create_app(auto_init=False).routes:
        for m in getattr(r, "methods", None) or []:
            if m not in ("HEAD", "OPTIONS"):
                seen[(m, r.path)].append(getattr(r, "name", "?"))
    assert {k: v for k, v in seen.items() if len(v) > 1} == {}
    src = (ROOT / "velora" / "api" / "app.py").read_text()
    calls = re.findall(r"^\s+(install_\w+)\(app", src, re.M)
    assert len(calls) == len(set(calls)), [c for c in calls if calls.count(c) > 1]


def test_openapi_has_no_duplicate_operation_ids():
    import warnings
    from velora.api import create_app
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        create_app(auto_init=False).openapi()
    assert [str(w.message) for w in caught if "Duplicate Operation ID" in str(w.message)] == []
