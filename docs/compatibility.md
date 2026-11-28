# What Velora runs on

Velora needs **Python 3.10 or newer** and, for a server, **PostgreSQL 13 or newer** (SQLite is fine for development). It does not need a particular Ubuntu: the installers work out the rest.

## Systems
| System | Python it ships | PostgreSQL it ships | What happens |
|---|---|---|---|
| **Ubuntu 26.04 LTS** (April 2026) | 3.13 / 3.14 | 18 | Works as is. |
| **Ubuntu 24.04 LTS** | 3.12 | 16 | Works as is. **The system the tests ran on.** |
| **Ubuntu 22.04 LTS** | 3.10 | 14 | Works as is (the minimum Python is 3.10 for exactly this reason). |
| **Ubuntu 20.04** | 3.8 | 12 | Works: the installer downloads a **private Python** and adds the **official PostgreSQL repository**. Standard support has ended. |
| **Ubuntu 18.04** | 3.6 | 10 | **End of life (2023).** Not for a production server: `install.sh` refuses unless you add `--allow-eol`. Fine for **development** with `install-dev.sh`. To keep the machine, `sudo do-release-upgrade` to 20.04 and then 22.04. |
| **Debian 12 / 13** | 3.11 / 3.13 | 15 / 17 | Works as is. |
| **Debian 11** | 3.9 | 13 | Works: private Python. |
| Others (Fedora, macOS, ...) | | | Not checked. Install Python 3.10+ and PostgreSQL 13+ yourself, then `pip install velora`; `install-dev.sh` also works on macOS. |

`velora doctor` tells you which row you are on and anything to fix. A PostgreSQL older than 13 is refused with the fix before anything is touched.

## How the installers cope with old systems
* **A private Python.** On a system whose Python is too old, the installer downloads the `uv` tool (its published checksum is verified), and with it a separate Python 3.12 kept in `/srv/velora/python`. The system Python is never touched, and there is no PPA. Choose another with `--python-version 3.13`.
* **The official PostgreSQL repository.** On 20.04 and Debian 11 it adds the signed `apt.postgresql.org` repository for your release and installs PostgreSQL 16 (`--pg-version 17` to choose).
* **Servers:** `sudo bash install.sh --email you@company.com`. **Developer machines (any Ubuntu from 18.04, macOS):** `bash install-dev.sh`, which needs no root and installs into `~/.velora`, then `velora quickstart`.

## What was actually tested
Honest evidence, so you know how much to trust each row:
* **Python:** the full test suite was run on **3.10** (the lowest supported), **3.12** and **3.14** (the newest), on SQLite and on PostgreSQL 16. On 3.14 the dependencies resolve to SQLAlchemy 2.1; nothing needed changing.
* **PostgreSQL:** tested on **16** only. 13, 14, 15, 17 and 18 are expected to work (no feature is used that they lack, and 13 is the floor for `DROP DATABASE ... WITH (FORCE)`), but were not available to test.
* **Operating systems:** only **Ubuntu 24.04** ran the tests. The other rows follow from what each ships and what the installer does about it; the installer's decisions for every row are tested by dry runs. `install-dev.sh` was run for real (downloading a private Python 3.10 beside the system's 3.12). `install.sh` has **not** been run end to end on a fresh server of any version: try it on a spare machine first.

## Seeing and trying Ubuntu versions
Download the images from **ubuntu.com/download** (server and desktop; 24.04 and 26.04 are listed under their LTS releases). Older images, including 24.04, are at **releases.ubuntu.com/24.04**. To try Velora without touching a real machine, run an Ubuntu virtual machine (Multipass, VirtualBox or your host's snapshot feature) and run the installer there. Your hosting provider's control panel shows which Ubuntu versions it can provision.
