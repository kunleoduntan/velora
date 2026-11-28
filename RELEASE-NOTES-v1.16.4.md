# Velora 1.16.4 - install an app you added with pip, by name
- **Fixed**: `velora install-app velora_admin` (or any Velora app added with `pip install`) was refused with "is not an app in this workspace" unless the app was also in the workspace's apps folder or given as a git URL. A pip-installed Velora app is now recognised by name, registered in the workspace, and installed on every company in one step.
- A module that is importable but is not a Velora app (no `hooks.py`) is still refused.

After `pip install` of a new application, install it on the companies:
`sudo -u velora VELORA_WORKSPACE=/srv/velora/workspace /srv/velora/venv/bin/velora install-app velora_admin`
