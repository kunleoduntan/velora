"""Run ONE server script as an attacker would, in its own process (so a hang or memory blow-up is contained). Used by test_script_sandbox_limits.py; prints a one-line verdict."""
import resource
import sys
import tempfile
import time
import warnings

resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 ** 3, 3 * 1024 ** 3))
warnings.simplefilter("ignore")
sys.path[:0] = sys.argv[2:]
import velora  # noqa: E402

velora.init(velora.configure(db_url=f"sqlite:///{tempfile.mkdtemp()}/a.db", apps=["velora_demo"], developer_mode=True)); velora.migrate()
from velora import new_doc, scripts  # noqa: E402
from velora.exceptions import ValidationError  # noqa: E402

doc, started = new_doc("Customer", customer_name="Victim"), time.time()
try:
    scripts._run_server_script({"code": sys.argv[1], "name": "attack"}, doc)
    verdict = "RAN"
except MemoryError:
    verdict = "MEMORY"
except ValidationError as e:
    verdict = "REFUSED " + str(e)
except Exception as e:  # noqa: BLE001
    verdict = f"RAW {type(e).__name__}"
print(f"VERDICT {verdict} | seconds={time.time() - started:.1f} docstatus={doc.docstatus!r} owner={doc.owner!r} name={doc.name!r}")
