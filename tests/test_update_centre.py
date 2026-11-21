"""Update Centre: drop-folder scanning, upload rules and the step-by-step job."""
import io, json, zipfile
from pathlib import Path
import pytest
from velora.exceptions import ValidationError
from velora.upgrade import dropfolder as drop


class WS:
    def __init__(self, root): self.root = Path(root)
    def common_config(self): return {"update": {"restart_command": "echo restart"}}
    def apps(self): return ["velora_erp"]


def wheel_bytes():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x/__init__.py", "")
    return b.getvalue()


def test_only_valid_wheels_are_accepted(tmp_path):
    ws = WS(tmp_path)
    assert drop.save_upload(ws, "velora-9.9.9-py3-none-any.whl", wheel_bytes())["file"].endswith(".whl")
    for bad in ("notes.txt", "velora.whl", "../../etc/passwd"):
        with pytest.raises(ValidationError):
            drop.save_upload(ws, bad, wheel_bytes())
    with pytest.raises(ValidationError, match="not a valid wheel"):
        drop.save_upload(ws, "velora-9.9.10-py3-none-any.whl", b"plainly not a zip")


def test_scan_flags_newer_and_keeps_the_newest_per_package(tmp_path):
    ws = WS(tmp_path)
    for n in ("velora-9.9.8-py3-none-any.whl", "velora-9.9.9-py3-none-any.whl", "velora_erp-0.0.1-py3-none-any.whl"):
        drop.save_upload(ws, n, wheel_bytes())
    rows = {r["package"]: r for r in drop.scan(ws)}
    assert rows["velora"]["version"] == "9.9.9" and rows["velora"]["newer"]
    assert rows["velora-erp"]["newer"] is True or rows["velora-erp"]["installed"] is not None


def test_nothing_to_do_and_double_start_are_refused(tmp_path):
    ws = WS(tmp_path)
    with pytest.raises(ValidationError, match="nothing newer"):
        drop.start(ws, spawn=lambda cmd: None)
    drop.save_upload(ws, "velora-9.9.9-py3-none-any.whl", wheel_bytes())
    jid = drop.start(ws, actor="a@b.c", spawn=lambda cmd: None)
    assert drop.running_job(ws)["id"] == jid
    with pytest.raises(ValidationError, match="already running"):
        drop.start(ws, spawn=lambda cmd: None)


def test_job_runs_every_step_in_order_and_stops_with_maintenance_on_when_a_step_fails(tmp_path):
    ws = WS(tmp_path)
    drop.save_upload(ws, "velora-9.9.9-py3-none-any.whl", wheel_bytes())
    jid = drop.start(ws, spawn=lambda cmd: None)
    seen = []
    done = drop.execute(ws, jid, runner=lambda job, cmd, label: seen.append(label))
    assert done["state"] == "done"
    assert seen == ["Maintenance mode on", "Install new code", "Upgrade databases", "install-app velora_erp", "Maintenance mode off", "Restart"]

    drop.drop_dir(ws)
    (drop.drop_dir(ws) / "jobs" / f"{jid}.json").unlink()
    jid2 = "20990101-000000"
    job = drop.Job(ws, jid2); job.doc.update(files=["velora-9.9.9-py3-none-any.whl"]); job.save()
    def failing(job, cmd, label):
        if label == "Upgrade databases":
            raise RuntimeError("boom")
    out = drop.execute(ws, jid2, runner=failing)
    assert out["state"] == "failed" and "boom" in out["error"]
    states = {s["name"]: s["state"] for s in out["steps"]}
    assert states["Install new code"] == "done" and states["Upgrade databases"] == "running" and states["Maintenance mode off"] == "pending"
    assert any("left ON on purpose" in line for line in out["log"])
