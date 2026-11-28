"""The server installer and uninstaller: one command each (checked with --dry-run; nothing real is installed)."""
import os
import re
import shutil
import sys
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).parent.parent / "deploy"


def sh(script, *args, stdin=subprocess.DEVNULL):
    r = subprocess.run(["bash", str(DEPLOY / script), *args], capture_output=True, text=True, stdin=stdin, timeout=60)
    return r.returncode, r.stdout, r.stderr


@pytest.mark.parametrize("script", ["install.sh", "uninstall.sh", "velora-domain", "install-dev.sh"])
def test_scripts_are_valid_shell(script):
    assert subprocess.run(["bash", "-n", str(DEPLOY / script)]).returncode == 0
    if shutil.which("shellcheck"):
        r = subprocess.run(["shellcheck", "-S", "warning", str(DEPLOY / script)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout


def test_one_install_command_sets_up_everything_with_one_service():
    code, out, _ = sh("install.sh", "--dry-run", "--email", "a@b.co", "--domain", "erp.example.com", "--extras", "pdf,data", "--auto-update", "daily")
    assert code == 0
    for step in ("1/7 System packages", "2/7 Service user", "3/7 Velora", "4/7 PostgreSQL", "5/7 First company", "6/7 Service", "7/7 Web server"):
        assert step in out
    assert out.count("velora.service") >= 1 and "velora-worker" not in out                                            # ONE service: the worker runs inside it
    assert "background worker" in out and "/usr/local/bin/velora" in out and "velora-update.timer" in out and "certbot" in out
    assert "sudo velora update" in out and "sudo velora install-app" in out and "sudo bash uninstall.sh" in out       # what to type next, all short


def test_extras_are_installed_after_the_workspace_exists_so_update_remembers_them():
    out = sh("install.sh", "--dry-run", "--email", "a@b.co", "--extras", "pdf,data")[1]
    assert out.index("velora quickstart") < out.index("deps install pdf data")                                        # (otherwise nothing could record them)
    assert "VELORA_WORKSPACE=/srv/velora/workspace" in out


def test_no_extras_no_domain_no_timer_means_none_of_them():
    out = sh("install.sh", "--dry-run", "--email", "a@b.co")[1]
    assert "deps install" not in out and "nginx site" not in out and "velora-update.timer" not in out and "listens on 127.0.0.1" in out


@pytest.mark.parametrize("args,frag", [(["--dry-run"], "--email is required"), (["--dry-run", "--email", "nope"], "is not an email"), (["--dry-run", "--email", "a@b.co", "--auto-update", "hourly"], "daily or weekly"),
                                       (["--dry-run", "--email", "a@b.co", "--wat"], "Unknown option")])
def test_the_installer_refuses_bad_input_clearly(args, frag):
    code, out, err = sh("install.sh", *args)
    assert code == 2 and frag in err


def installer_text():
    return (DEPLOY / "install.sh").read_text()


def test_the_velora_command_wrapper_is_valid_and_runs_as_the_service_user_in_the_workspace(tmp_path):
    s = installer_text()
    body = re.search(r"cat > /usr/local/bin/velora <<WRAPEOF\n(.*?)\nWRAPEOF", s, re.S).group(1)
    body = body.replace("$ROOT", "/srv/velora").replace("\\$", "$")                                                   # what the installer's heredoc expands it to
    f = tmp_path / "velora"
    f.write_text(body + "\n")
    assert subprocess.run(["sh", "-n", str(f)]).returncode == 0
    assert 'export VELORA_WORKSPACE="/srv/velora/workspace"' in body and "runuser -u velora" in body and "sudo -u velora" in body and 'exec "/srv/velora/venv/bin/velora" "$@"' in body


def test_rerunning_the_installer_restarts_the_service_onto_the_new_code():
    s = installer_text()
    assert "systemctl restart velora" in s and "systemctl enable --now velora\n" not in s                              # enable --now would leave the OLD code running on a re-run
    assert 'auto_upgrade=c.get("auto_upgrade", True)' in s                                                                  # and the server upgrades databases itself when it starts


def test_uninstall_keeps_your_data_by_default():
    code, out, _ = sh("uninstall.sh", "--dry-run")
    assert code == 0 and "Final backup" in out and "backup --all" in out and "master.key" in out                       # always a backup first
    assert "Kept: /srv/velora" in out and "rm -rf /srv/velora" not in out and "company drop" not in out and "userdel" not in out
    assert "systemctl disable --now velora.service" in out and "rm -f /etc/systemd/system/velora.service" in out and "/usr/local/bin/velora" in out


def test_purge_removes_everything_after_saving_a_backup_outside_the_workspace():
    code, out, _ = sh("uninstall.sh", "--dry-run", "--purge", "--root", "/opt/velora-x")
    assert code == 0
    assert out.index("backup --all") < out.index("company drop") < out.index("DROP DATABASE + ROLE of the control plane") < out.index("rm -rf /opt/velora-x")      # backup, companies, control plane, then files
    assert "/root/velora-final-backup-" in out and "DROP ROLE velora_root" in out and "userdel velora" in out and "/srv/velora" not in out         # --root is honoured everywhere


@pytest.mark.skipif(os.geteuid() != 0, reason="the script checks for root first; this test exercises the confirmation step")
def test_uninstall_will_not_proceed_without_confirmation_when_not_at_a_terminal():
    code, out, err = sh("uninstall.sh", "--root", "/nonexistent-velora-root")
    assert code == 1 and "not a terminal; re-run with --yes" in err and "Final backup" not in out                       # refused BEFORE doing anything
    code, _, err = sh("uninstall.sh", "--dry-run", "--wat")
    assert code == 2 and "Unknown option" in err
    code, out, _ = sh("uninstall.sh", "--yes", "--root", "/nonexistent-velora-root", "--dry-run")
    assert code == 0 and "Nothing to back up" not in out                                                                # (dry run lists what it WOULD do)


def test_the_help_leads_with_the_everyday_one_step_commands(capsys):
    from velora.cli import main
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for cmd in ("velora quickstart", "velora install-app APP", "velora update", "velora uninstall-app APP", "velora doctor", "install.sh installs everything in one command"):
        assert cmd in out


def test_the_purge_drops_the_control_plane_database_but_only_a_name_velora_generated():
    text = (DEPLOY / "uninstall.sh").read_text()
    assert "control_plane.json" in text and "provisioned_db" in text and "WITH (FORCE)" in text
    pattern = re.search(r'\[\[ "\$CPNAME" =~ (\S+) \]\]', text).group(1)
    ok = re.compile(pattern)
    assert ok.match("velora_cp_e657eee34443") and not ok.match("postgres") and not ok.match("velora_cp_") and not ok.match('velora_cp_ab"; DROP DATABASE x; --') and not ok.match("velora_test")


def test_the_installer_lets_its_database_role_use_the_roles_it_creates_on_postgresql_16_and_later():
    """Regression: on PostgreSQL 16+ a CREATEROLE role cannot use the roles it creates unless createrole_self_grant is set, so the very first company failed."""
    text = installer_text()
    assert "createrole_self_grant = 'set, inherit'" in text and "-ge 160000" in text
    assert text.index("CREATE ROLE velora_root") < text.index("ALTER ROLE velora_root SET createrole_self_grant")      # set after the role exists


@pytest.mark.skipif(os.geteuid() != 0, reason="the script checks for root first")
def test_a_purge_that_could_not_drop_the_databases_refuses_before_changing_anything(tmp_path):
    """Regression (found by running it for real): a purge without the database password used to skip the databases silently, then delete the files that held their credentials."""
    ws = tmp_path / "workspace"
    (ws / "platform").mkdir(parents=True)
    (ws / "platform" / "master.key").write_text("k")
    code, out, err = sh("uninstall.sh", "--purge", "--yes", "--root", str(tmp_path))
    assert code == 1 and "cannot purge safely" in err and "Nothing was changed" in err
    assert (ws / "platform" / "master.key").exists() and "Final backup" not in out                                      # nothing deleted, no backup attempted, nothing orphaned


def test_the_purge_never_deletes_the_files_after_a_failed_database_drop():
    text = (DEPLOY / "uninstall.sh").read_text()
    assert text.count("FAILED=1") == 2 and 'if [ "$FAILED" = 1 ]' in text
    assert text.index('if [ "$FAILED" = 1 ]') < text.index('run rm -rf "$ROOT"')                                       # the check comes BEFORE the files are removed


def helper(*args):
    r = subprocess.run(["bash", str(DEPLOY / "velora-domain"), *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
    return r.returncode, r.stdout, r.stderr


def test_the_installer_points_at_the_tutorial_with_the_right_address():
    assert "Tutorial:  http://localhost:8000/tutorial" in sh("install.sh", "--dry-run", "--email", "a@b.co")[1]
    out = sh("install.sh", "--dry-run", "--email", "a@b.co", "--domain", "erp.x.com")[1]
    assert "Tutorial:  https://erp.x.com/tutorial" in out and "erp.x.comerp.x.com" not in out


@pytest.mark.parametrize("domain", ["bad;rm -rf /", "a.com && reboot", "$(id).com", "-x.com", "x-.com", "nodots", "UPPER.com", "a..com", "a.com\nb.com", "", "ünï.com", "a.com/../../etc", "a b.com"])
def test_the_root_helper_trusts_nothing_it_is_given(domain):
    code, _, err = helper("add", domain, "--dry-run")
    assert code == 2 and "not a valid domain name" in err or code == 2                                                  # every hostile name is refused before anything is touched


@pytest.mark.parametrize("args,frag", [(["add", "a.com", "--port", "99999"], "invalid port"), (["add", "a.com", "--port", "80; id"], "invalid port"), (["add", "a.com", "--port", "0"], "invalid port"),
                                       (["add", "a.com", "--email", "x@y"], "invalid email"), (["add", "a.com", "--email", "a@b.co;id"], "invalid email"), (["add", "a.com", "--wat"], "Unknown option"),
                                       (["frobnicate", "a.com"], "action must be add or remove")])
def test_the_root_helper_validates_every_option(args, frag):
    code, _, err = helper(*args, "--dry-run")
    assert code == 2 and frag in err


def test_the_root_helper_dry_run_shows_exactly_what_it_would_do():
    code, out, _ = helper("add", "erp.acme.com", "--port", "8001", "--email", "ops@acme.ng", "--dry-run")
    assert code == 0
    assert "write /etc/nginx/sites-available/velora-erp.acme.com" in out and "server_name erp.acme.com;" in out and "proxy_pass http://127.0.0.1:8001;" in out
    assert "proxy_set_header Host $host" in out and "location /api/events" in out and "proxy_buffering off" in out                      # the company is chosen from Host; live notifications are never buffered
    assert "certbot --nginx -d erp.acme.com --non-interactive --agree-tos -m ops@acme.ng --redirect" in out
    assert "certbot" not in helper("add", "erp.acme.com", "--no-tls", "--dry-run")[1]
    out = helper("remove", "erp.acme.com", "--dry-run")[1]
    assert "rm -f /etc/nginx/sites-enabled/velora-erp.acme.com /etc/nginx/sites-available/velora-erp.acme.com" in out


@pytest.mark.skipif(os.geteuid() == 0, reason="as root the helper would really run")
def test_the_root_helper_refuses_to_run_without_root():
    code, _, err = helper("add", "erp.acme.com")
    assert code == 1 and "must run as root" in err


def test_the_helper_embedded_in_the_installer_is_exactly_the_file():
    """install.sh must work on its own (curl | bash), so it carries a copy of the helper. The copy must never drift."""
    m = re.search(r"cat > /usr/local/sbin/velora-domain <<'DOMAINHELPER'\n(.*?)\nDOMAINHELPER\n", installer_text(), re.S)
    assert m, "the installer does not embed the helper"
    assert m.group(1) == (DEPLOY / "velora-domain").read_text().rstrip("\n")


def test_sudoers_allows_exactly_two_things_and_the_uninstaller_removes_them():
    s = installer_text()
    assert "'velora ALL=(root) NOPASSWD: /bin/systemctl restart velora' 'velora ALL=(root) NOPASSWD: /usr/local/sbin/velora-domain'" in s
    assert s.count("NOPASSWD") == 2 and "NOPASSWD: ALL" not in s                                                          # never a blanket grant
    assert '"helper": "sudo -n /usr/local/sbin/velora-domain"' in s
    u = (DEPLOY / "uninstall.sh").read_text()
    assert "/usr/local/sbin/velora-domain" in u and "sites-enabled/velora-*" in u and "sites-available/velora-*" in u
    assert "velora-*" in sh("uninstall.sh", "--dry-run")[1]


# ============================== other Ubuntu/Debian versions ==============================
def os_file(tmp_path, ident, ver, codename="", pretty=None):
    f = tmp_path / f"os-{ident}-{ver}"
    f.write_text(f'ID={ident}\nVERSION_ID="{ver}"\nVERSION_CODENAME={codename}\nPRETTY_NAME="{pretty or ident.title() + " " + ver}"\n')
    return f


def install_for(tmp_path, ident, ver, codename="", *args, env=None):
    import os as _os
    f = os_file(tmp_path, ident, ver, codename)
    r = subprocess.run(["bash", str(DEPLOY / "install.sh"), "--dry-run", "--email", "a@b.co", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
                       env={**_os.environ, "VELORA_OS_RELEASE": str(f), **(env or {})})
    return r.returncode, r.stdout, r.stderr


@pytest.mark.parametrize("ident,ver,code", [("ubuntu", "22.04", "jammy"), ("ubuntu", "24.04", "noble"), ("ubuntu", "26.04", "resolute"), ("debian", "12", "bookworm"), ("debian", "13", "trixie")])
def test_recent_systems_use_their_own_python_and_postgresql_with_no_extra_steps(tmp_path, ident, ver, code):
    rc, out, _ = install_for(tmp_path, ident, ver, code)
    assert rc == 0
    assert "apt-get install -y -qq postgresql postgresql-client python3 python3-venv python3-pip" in out                 # the system's own, as is
    assert "uv python install" not in out and "pgdg" not in out and "Note:" not in out                                  # nothing private, no extra repository, no warnings
    assert "python3 -m venv /srv/velora/venv" in out


@pytest.mark.parametrize("ident,ver,code", [("ubuntu", "20.04", "focal"), ("debian", "11", "bullseye")])
def test_older_systems_get_a_private_python_and_the_official_postgresql_repository(tmp_path, ident, ver, code):
    rc, out, _ = install_for(tmp_path, ident, ver, code)
    assert rc == 0 and "a private Python and the official PostgreSQL repository will be used" in out
    assert f"apt.postgresql.org/pub/repos/apt {code}-pgdg main" in out and "signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc" in out        # a signed repository for THIS release
    assert "apt-get install -y -qq postgresql-16 postgresql-client-16" in out and "python3-venv" not in out               # the system Python is not even installed or used
    assert "uv python install 3.12" in out and "UV_PYTHON_INSTALL_DIR" not in out and "uv venv --seed --python 3.12 /srv/velora/venv" in out


def test_ubuntu_18_04_is_refused_for_a_server_with_the_way_forward(tmp_path):
    rc, out, err = install_for(tmp_path, "ubuntu", "18.04", "bionic")
    assert rc == 1 and "reached end of life in 2023" in err and "do-release-upgrade" in err and "install-dev.sh" in err and "--allow-eol" in err
    assert "apt-get" not in out                                                                                          # it stopped before touching anything
    rc, out, _ = install_for(tmp_path, "ubuntu", "18.04", "bionic", "--allow-eol")
    assert rc == 0 and "WARNING" in out and "uv python install" in out and "bionic-pgdg" in out                         # at your own risk, with the same fixes as 20.04


def test_an_unknown_system_is_warned_not_refused(tmp_path):
    rc, out, _ = install_for(tmp_path, "linuxmint", "21", "vanessa")
    assert rc == 0 and "has not been checked with Velora" in out and "Python 3.10+ and PostgreSQL 13+" in out


def test_python_and_postgresql_versions_can_be_chosen_and_are_validated(tmp_path):
    rc, out, _ = install_for(tmp_path, "ubuntu", "20.04", "focal", "--python-version", "3.13", "--pg-version", "17")
    assert rc == 0 and "uv python install 3.13" in out and "postgresql-17 postgresql-client-17" in out
    for args, frag in ((["--python-version", "3.9"], "3.10 to 3.19"), (["--python-version", "3.12; id"], "3.10 to 3.19"), (["--pg-version", "12"], "13 or newer"), (["--pg-version", "x"], "13 or newer")):
        rc, _, err = install_for(tmp_path, "ubuntu", "22.04", "jammy", *args)
        assert rc == 2 and frag in err


def test_a_private_python_can_be_forced_and_the_old_python_311_requirement_is_gone(tmp_path):
    rc, out, _ = install_for(tmp_path, "ubuntu", "22.04", "jammy", env={"VELORA_FORCE_PRIVATE_PYTHON": "1"})
    assert rc == 0 and "uv python install 3.12" in out
    text = installer_text()
    assert "3, 11" not in text and "Python 3.11+" not in text and "deadsnakes" not in text                              # it no longer blocks Ubuntu 22.04
    assert "sys.version_info >= (3, 10)" in text and "-ge 130000" in text                                                # the real minimums: Python 3.10, PostgreSQL 13


def test_the_uv_download_function_is_identical_in_both_installers_and_verifies_its_download():
    pat = re.compile(r"# ---- BEGIN install_uv.*?# ---- END install_uv", re.S)
    a, b = pat.search(installer_text()).group(0), pat.search((DEPLOY / "install-dev.sh").read_text()).group(0)
    assert a == b
    assert "sha256sum -c" in a and ".sha256" in a and "https://github.com/astral-sh/uv/releases" in a and "failed its checksum; not using it" in a
    for triple in ("x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu", "aarch64-apple-darwin", "x86_64-apple-darwin"):
        assert triple in a


# ============================== install-dev.sh ==============================
def dev(*args):
    r = subprocess.run(["bash", str(DEPLOY / "install-dev.sh"), *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    return r.returncode, r.stdout, r.stderr


def test_the_developer_installer_needs_no_root_and_changes_nothing_on_the_system():
    code, out, _ = dev("--dry-run", "--dir", "/tmp/vdev", "--python", "3.13", "--extras", "pdf,data")
    assert code == 0 and "uv python install 3.13" in out and "your system Python is not touched" in out and "/tmp/vdev/venv" in out and "uv pip install velora (extras: pdf,data)" in out
    assert "ln -sf /tmp/vdev/venv/bin/velora" in out and ".local/bin/velora" in out and "Next: velora quickstart" in out
    text = (DEPLOY / "install-dev.sh").read_text()
    assert "sudo" not in text.replace("sudo apt install curl", "") and "apt-get" not in text and "/etc/" not in text and "systemctl" not in text


@pytest.mark.parametrize("args,frag", [(["--python", "3.8"], "3.10 to 3.19"), (["--extras", "pdf;rm"], "comma-separated"), (["--wat"], "Unknown option"), (["--source"], "")])
def test_the_developer_installer_refuses_bad_input(args, frag):
    code, _, err = dev("--dry-run", *args)
    assert code != 0 and frag in err


def test_the_developer_installer_can_install_from_a_wheel_file_or_a_name():
    out = dev("--dry-run", "--source", "/tmp/velora-0.9-py3-none-any.whl")[1]
    assert "uv pip install /tmp/velora-0.9-py3-none-any.whl" in out


def test_the_developer_installer_can_create_and_start_everything_in_one_command():
    code, out, _ = dev("--dry-run", "--workspace", "/tmp/my-erp", "--email", "you@company.com", "--company", "Acme Ltd")
    assert code == 0 and 'velora quickstart /tmp/my-erp --email you@company.com --company "Acme Ltd"' in out and "then starts it" in out and "--no-start" not in out
    code, out, _ = dev("--dry-run", "--workspace", "/tmp/my-erp", "--email", "you@company.com", "--no-start")
    assert code == 0 and "velora quickstart /tmp/my-erp --email you@company.com --no-start" in out
    text = (DEPLOY / "install-dev.sh").read_text()
    assert 'exec "${QS[@]}"' in text and "--no-start" in text


@pytest.mark.parametrize("args,frag", [(["--workspace", "/tmp/x"], "needs --email"), (["--email", "a@b.co"], "only apply with --workspace"), (["--company", "X"], "only apply with --workspace"),
                                       (["--workspace", "/tmp/x", "--email", "not-an-email"], "not an email address"), (["--workspace", "/tmp/x", "--email", "a b@c.d"], "not an email address")])
def test_the_one_command_installer_refuses_a_half_given_setup(args, frag):
    code, _, err = dev("--dry-run", *args)
    assert code == 2 and frag in err


# ============================== the installer's settings step is EXECUTED, not only dry-run ==============================
def _settings_block(root, source="git+https://github.com/me/velora.git@main", port=8000, email="a@b.co"):
    """The python that install.sh runs in step 6, with its shell variables filled in the way the shell would."""
    text = installer_text()
    block = text.split("<<CONFIGEND\n", 1)[1].split("\nCONFIGEND", 1)[0]
    return block.replace("$ROOT", str(root)).replace("$SOURCE", source).replace("$PORT", str(port)).replace("$EMAIL", email)


def test_the_installers_settings_step_works_on_a_real_new_layout_workspace_and_keeps_what_quickstart_wrote(tmp_path):
    import json
    from velora import quickstart as qs
    res = qs.quickstart(str(tmp_path / "workspace"), email="boss@acme.ng", password="a long passphrase 1", company="Acme", log=lambda *_: None)
    ws_root = Path(res["workspace"])
    before = json.loads((ws_root / "config" / "common.json").read_text())
    assert "default_apps" in before
    r = subprocess.run([sys.executable, "-c", _settings_block(ws_root.parent)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]                                                             # it used to die with FileNotFoundError: sites/common_site_config.json
    after = json.loads((ws_root / "config" / "common.json").read_text())
    assert after["update"] == {"restart_command": "sudo -n /bin/systemctl restart velora", "framework_source": "git+https://github.com/me/velora.git@main"}
    assert after["domain"] == {"helper": "sudo -n /usr/local/sbin/velora-domain", "port": 8000, "email": "a@b.co"}
    assert after["auto_upgrade"] is True and after["default_apps"] == before["default_apps"]               # nothing quickstart wrote was lost
    assert not (ws_root / "sites").exists()                                                               # and no legacy folder was created


def test_the_settings_step_is_safe_to_run_twice_and_keeps_an_existing_choice(tmp_path):
    import json
    from velora import quickstart as qs
    ws_root = Path(qs.quickstart(str(tmp_path / "workspace"), email="boss@acme.ng", password="a long passphrase 1", company="Acme", log=lambda *_: None)["workspace"])
    from velora.workspace import Workspace
    Workspace(ws_root).update_config(auto_upgrade=False, update={"channel": "stable"})
    for _ in range(2):
        assert subprocess.run([sys.executable, "-c", _settings_block(ws_root.parent)], capture_output=True, text=True, timeout=60).returncode == 0
    c = json.loads((ws_root / "config" / "common.json").read_text())
    assert c["auto_upgrade"] is False and c["update"]["channel"] == "stable" and c["update"]["framework_source"].startswith("git+https")   # a person's choice survives a re-run


def test_the_settings_step_still_works_on_an_older_workspace_that_keeps_its_settings_in_sites(tmp_path):
    import json
    root = tmp_path / "workspace"
    (root / "sites").mkdir(parents=True)
    (root / "sites" / "apps.txt").write_text("")
    (root / "sites" / "common_site_config.json").write_text('{"developer_mode": false}')
    r = subprocess.run([sys.executable, "-c", _settings_block(tmp_path)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-300:]
    assert json.loads((root / "sites" / "common_site_config.json").read_text())["update"]["framework_source"].startswith("git+https")     # it writes where the file IS


def test_no_deployment_script_hard_codes_a_settings_path():
    for name in ("install.sh", "uninstall.sh", "velora-domain", "install-dev.sh"):
        text = (DEPLOY / name).read_text()
        for legacy in ("common_site_config", "sites/apps.txt", "lifecycle_log", "workspace/sites"):
            assert legacy not in text, f"{name} hard-codes {legacy}: ask Velora (Workspace.common_config_file) where its settings are"
