"""Sign-in hardening: the second factor counts against the account, a code works once, and the counters cannot be beaten by parallel requests."""
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from velora.controlplane import ControlPlane
from velora.controlplane import identity as ident
from velora.controlplane import models as m
from velora.controlplane.identity import _totp_counter
from velora.exceptions import AuthenticationRequired
from velora.workspace import Workspace

PW = "long secure password"


def step_now():
    return int(datetime.now(timezone.utc).timestamp() // 30)


@pytest.fixture
def plane(tmp_path, monkeypatch):
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    p = ControlPlane.create(Workspace.create(tmp_path / "ws"), admin_email="boss@example.com", admin_password=PW)
    yield p
    p.dispose()


def user_row(plane, email="boss@example.com"):
    with plane.engine.connect() as c:
        return dict(c.execute(select(m.user).where(m.user.c.email == email)).mappings().first())


def with_mfa(plane):
    """Enrol the admin in TOTP; returns the secret."""
    auth = plane.identity.authenticate("boss@example.com", PW).context
    secret = plane.identity.begin_totp(auth)["secret"]
    plane.identity.confirm_totp(auth, _totp_counter(secret, step_now()))
    return secret


# ============================== the second factor is not guessable at leisure ==============================
def test_wrong_authenticator_codes_lock_the_account_even_from_changing_addresses(plane):
    with_mfa(plane)
    for n in range(ident.MAX_FAILED):
        with pytest.raises(AuthenticationRequired, match="authenticator code is invalid"):
            plane.identity.authenticate("boss@example.com", PW, ip=f"198.51.100.{n}", totp_code="000000")           # a different address each time: only the ACCOUNT can stop this
    secret_code = _totp_counter(plane.secrets.get(user_row(plane)["totp_secret_ref"]), step_now() + 1)
    with pytest.raises(AuthenticationRequired, match="temporarily locked"):
        plane.identity.authenticate("boss@example.com", PW, ip="198.51.100.99", totp_code=secret_code)             # even the RIGHT code is refused while locked
    assert user_row(plane)["locked_until"] > datetime.utcnow()


def test_not_supplying_a_code_is_not_a_failed_guess(plane):
    with_mfa(plane)
    for _ in range(ident.MAX_FAILED + 2):
        with pytest.raises(AuthenticationRequired, match="six-digit"):
            plane.identity.authenticate("boss@example.com", PW)                                                     # the sign-in form asking for the code must never lock anyone
    assert user_row(plane)["failed_attempts"] == 0 and user_row(plane)["locked_until"] is None


def test_each_code_works_once_and_older_codes_never_work_again(plane):
    secret = with_mfa(plane)                                                    # enrolment consumed the current step
    now = step_now()
    code = lambda k: _totp_counter(secret, now + k)                             # noqa: E731
    with pytest.raises(AuthenticationRequired, match="invalid"):
        plane.identity.authenticate("boss@example.com", PW, totp_code=code(0))   # the code that confirmed the setup: already used
    assert plane.identity.authenticate("boss@example.com", PW, totp_code=code(1)).token
    with pytest.raises(AuthenticationRequired, match="invalid"):
        plane.identity.authenticate("boss@example.com", PW, totp_code=code(1))   # the same code again (a shoulder-surfer, a replay): refused
    with pytest.raises(AuthenticationRequired, match="invalid"):
        plane.identity.authenticate("boss@example.com", PW, totp_code=code(-1))  # an EARLIER step than one already accepted: refused
    assert user_row(plane)["totp_last_step"] == now + 1


def test_two_requests_presenting_the_same_code_together_only_one_signs_in(plane):
    secret = with_mfa(plane)
    code = _totp_counter(secret, step_now() + 1)
    results, gate = [], threading.Barrier(8)

    def attempt():
        gate.wait()
        try:
            plane.identity.authenticate("boss@example.com", PW, totp_code=code)
            results.append("ok")
        except AuthenticationRequired:
            results.append("refused")
    threads = [threading.Thread(target=attempt) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("refused") == 7


def test_the_correct_code_resets_the_failure_count(plane):
    secret = with_mfa(plane)
    for _ in range(ident.MAX_FAILED - 1):
        with pytest.raises(AuthenticationRequired):
            plane.identity.authenticate("boss@example.com", PW, totp_code="000000")
    assert user_row(plane)["failed_attempts"] == ident.MAX_FAILED - 1
    assert plane.identity.authenticate("boss@example.com", PW, totp_code=_totp_counter(secret, step_now() + 1)).token
    assert user_row(plane)["failed_attempts"] == 0


# ============================== counters that parallel requests cannot beat ==============================
def hammer(fn, n):
    gate, errors = threading.Barrier(n), []

    def run():
        gate.wait()
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))
    ts = [threading.Thread(target=run) for _ in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return errors


def test_parallel_wrong_passwords_are_all_counted_and_the_account_locks(plane):
    plane.identity.create_user("target@example.com", "Target", PW)
    n = ident.MAX_FAILED * 3
    errors = hammer(lambda: plane.identity.authenticate("target@example.com", "wrong password here"), n)
    assert all("AuthenticationRequired" in e for e in errors)                                                   # refused (never a crash) ...
    row = user_row(plane, "target@example.com")
    assert row["locked_until"] is not None and row["failed_attempts"] == 0                                      # ... and counted EXACTLY: 15 failures = three full lock cycles, none lost


def test_parallel_first_failures_from_one_address_never_crash_and_are_all_counted(plane):
    errors = hammer(lambda: plane.identity._record_ip_attempt("203.0.113.7", False, datetime.utcnow()), 12)
    assert errors == []                                                                                         # used to be a primary-key crash on the second INSERT
    with plane.engine.connect() as c:
        assert c.execute(select(m.login_ip.c.attempts).where(m.login_ip.c.ip == "203.0.113.7")).scalar() == 12


def test_the_address_limiter_blocks_at_the_limit_and_a_success_does_not_erase_the_evidence(plane):
    ip = "203.0.113.9"
    for _ in range(10):
        with pytest.raises(AuthenticationRequired):
            plane.identity.authenticate("nobody@example.com", "x" * 14, ip=ip)
    assert plane.identity.authenticate("boss@example.com", PW, ip=ip).token                                     # the attacker's own valid account
    with plane.engine.connect() as c:
        assert c.execute(select(m.login_ip.c.attempts).where(m.login_ip.c.ip == ip)).scalar() == 10            # does NOT reset the count (it would enable unlimited password spraying)
    for _ in range(ident.IP_MAX_FAILED - 10):
        with pytest.raises(AuthenticationRequired):
            plane.identity.authenticate("nobody@example.com", "x" * 14, ip=ip)
    with pytest.raises(AuthenticationRequired, match="Too many sign-in attempts"):
        plane.identity.authenticate("boss@example.com", PW, ip=ip)                                              # blocked now, valid credentials and all


def test_an_expired_window_starts_again(plane):
    ip, then = "203.0.113.11", datetime.utcnow() - timedelta(minutes=ident.IP_WINDOW_MINUTES + 1)
    for _ in range(5):
        plane.identity._record_ip_attempt(ip, False, then)
    plane.identity._record_ip_attempt(ip, False, datetime.utcnow())
    with plane.engine.connect() as c:
        assert c.execute(select(m.login_ip.c.attempts).where(m.login_ip.c.ip == ip)).scalar() == 1


# ============================== existing installations ==============================
def test_an_existing_control_plane_gains_the_new_column_through_the_normal_upgrade(plane):
    with plane.engine.begin() as c:
        c.execute(text(f"ALTER TABLE {m.user.name} DROP COLUMN totp_last_step"))
    assert plane.migrate(dry_run=True) and any("totp_last_step" in line for line in plane.migrate(dry_run=True))     # an upgrade is pending ...
    plane.migrate()
    secret = with_mfa(plane)                                                                                    # ... and after it, sign-in with a second factor works
    assert plane.identity.authenticate("boss@example.com", PW, totp_code=_totp_counter(secret, step_now() + 1)).token
