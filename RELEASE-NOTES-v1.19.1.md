# Velora 1.19.1: publish on top, and install / update from GitHub

- **Publish on top of GitHub** (Publish to GitHub screen): when the repository already has commits this copy does not, the screen shows exactly which files would be added, changed and removed, and on Yes adds one new commit after the repository's history so it then holds this copy. Their history is kept. There is still no force-push.
- **Install / Update from GitHub** (same screen, app profiles): brings the app from the repository with the profile's saved token (private repositories work), then installs it in the profile's company. A new app is cloned and registered; an existing one only moves forward (fast-forward). If this server's copy has changes the repository does not, or the two have gone different ways, nothing is touched and the screen says what to do. Cache files left by running the app are not counted as changes. Required Python packages are installed, the configured restart command is run, and databases are upgraded by the normal start-up upgrade (with a backup).
- A profile can now name an app that is only on GitHub so far (tick "The app is only on GitHub so far").
- The refusal message for a repository with other commits now points to Publish on top.

VeloraERP 2.106.0 is unchanged and runs on this version.

## Update Centre fixes
- The update worker called `python -m velora`, which fails when the installed package has no `velora/__main__.py` ("No module named velora.__main__"). It now calls the command line directly (`velora.cli.main`).
- New first step **Check the update**: every wheel is opened and checked (name and version agree with the file, the package is inside, the framework wheel contains its command line) and the command line is run once, all **before** maintenance mode is turned on. A bad update now stops with nothing changed.
- When an update stops before maintenance was turned on, the log says so ("Nothing was changed"); it no longer claims maintenance was left on.
- pip installs the wheels with `--no-index`: it never waits on, or needs, the internet during an update.
- Apps already installed are upgraded by the database step and are no longer re-installed one by one. That loop restarted the server once per app in the middle of the update, called pip for each, and put back apps a company had removed. Only an app that is new in the update is installed, without a restart; the single restart comes at the end.
- `update.restart_command` may be a list as well as a string.

## Packaging
- VeloraERP's wheel now includes the sample print formats (Official Receipt, Payment Voucher, Receipt Voucher); they were missing on servers installed from wheels. A test now builds the wheels and fails if any data file is left out.
