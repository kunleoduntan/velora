# Installing Velora from your GitHub repository

This page uses the address `github.com/YOUR-USER/velora`; replace it with yours.

**What was tested.** A real git repository was built from this project and Velora was installed from it, updated from it twice (a new commit each time), and run: all with `git+file://` addresses on a
local repository, because the test machine cannot reach GitHub. Only the *authentication to github.com itself* (passwords, tokens, deploy keys) is not tested. Everything else is the same code path.

## 1. Put the code on GitHub (once)

```bash
cd velora                                   # the project folder
git init -b main
git add -A                                  # the .gitignore already keeps out node_modules, caches, keys, databases and backups
git status --short | head                   # look before you commit: nothing secret, and velora/desk/ IS listed
git commit -m "Velora"
git remote add origin git@github.com:YOUR-USER/velora.git
git push -u origin main
```

* **`velora/desk/` must be committed.** It is the built web interface (made by `scripts/build-desk.sh`). Without it an install from git works but has no Desk. The `.gitignore` in the project deliberately does not ignore it.
* Verified: a repository made this way tracks the Desk (3 files), tracks no key, database or backup, and installs with the Desk included.
* Make a **release** whenever you want a version people can pin: `git tag v0.49.2 && git push --tags`.

## 2. Install on a computer you work on (Linux or macOS, no root)

One command, from a public repository:

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR-USER/velora/main/deploy/install-dev.sh -o install-dev.sh
bash install-dev.sh --source "git+https://github.com/YOUR-USER/velora.git@main" --workspace ~/my-erp --email you@company.com
```

From a private repository, clone first (using your normal GitHub sign-in), then install from the clone:

```bash
git clone git@github.com:YOUR-USER/velora.git
bash velora/deploy/install-dev.sh --source "git+file://$PWD/velora" --workspace ~/my-erp --email you@company.com
```

What this does (verified, 9 seconds on a clean machine): downloads a private Python, installs Velora from the repository, creates the workspace, a company and the administrator, and starts it.
It prints the address and a one-time password. `--no-start` creates everything without starting. To pin a version use `@v0.49.2` or a commit instead of `@main`.

## 3. Install on a server (Ubuntu or Debian)

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR-USER/velora/main/deploy/install.sh -o install.sh
sudo bash install.sh --email you@company.com --source "git+https://github.com/YOUR-USER/velora.git@main"
```

This installs PostgreSQL (the official repository on older systems), a private Python when the system one is too old, Velora, a service, and optionally a domain and HTTPS (`--domain erp.company.com`).
`install.sh` itself has been tested only as dry runs for each operating system: try it on a spare server first.

**Private repository on a server.** The installer runs `pip` as a service user that has no GitHub access. Two ways that avoid putting secrets in it:

1. **Wheel (recommended).** On your own computer: `uv build --wheel`, then copy `dist/velora-<version>-py3-none-any.whl` to the server and
   `sudo bash install.sh --email you@company.com --source /path/to/velora-<version>-py3-none-any.whl`. (Installing from a wheel file is verified.)
2. **Deploy key.** Create a key pair, add the PUBLIC half under the repository's Settings > Deploy keys (read-only), and make the PRIVATE half readable by the service user.
   Then use `--source "git+ssh://git@github.com/YOUR-USER/velora.git@main"`. (Not tested here.)

**Never put a token in the address** (`git+https://TOKEN@github.com/...`): Velora remembers the update source in `config/common.json` as plain text (see below), so the token would be stored there.

## 4. Updating from GitHub

Push your changes to GitHub, then on the server:

```bash
velora update --check          # shows what is available, for example "velora 0.49.2 -> 0.49.3 available"
velora update --yes            # new code, backup, database upgrade on the new code, restart; rolls everything back if anything fails
```

The first time, tell it where to look; it remembers (verified):

```bash
velora update --framework-source "git+https://github.com/YOUR-USER/velora.git@main" --yes
```

The source is stored in `config/common.json` under `update.framework_source`, so every later `velora update` needs no option. Behind a service manager, add `--restart-command 'sudo systemctl restart velora'`.
`velora update` records what it did in plain language in `config/lifecycle.json`, which the welcome page shows.

## 5. Apps from GitHub

Your own apps (separate repositories) install on every company in one step:

```bash
velora install-app https://github.com/YOUR-USER/governmentone.git --branch main
velora update --app governmentone --yes       # later, to fetch that app's new commits
velora uninstall-app governmentone            # backs up first; the app's data is kept unless you say --purge
```

## 6. Moving to a new server

```bash
# old server
velora ops backup                                         # encrypted; or set VELORA_BACKUP_PASSWORD to run it from cron
# new server (nothing installed yet): install as in section 2 or 3, then
velora ops verify backups/workspace-....vbackup
velora ops restore-workspace backups/workspace-....vbackup --into ~/my-erp-restored
cd ~/my-erp-restored && velora doctor && velora start
```

PostgreSQL companies keep their data in PostgreSQL: back those up with `velora backup --all` and restore with `velora restore`. See `docs/disaster-recovery.md` and `docs/file-structure.md`.
