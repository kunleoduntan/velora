# Velora 1.16.3 - fixes the how-to guide links
- **Fixed an internal server error** when opening a how-to guide (`/guide/<app>`) on a server with more than one company: the page looked for a "current company" that does not exist on that public route. It now finds the guide from the app's own package, with no company or sign-in.
- The new test calls the real route with no stand-in, so this cannot come back unnoticed.
- **An application installed with pip must also be installed on the companies.** `pip install` only puts an app on the server; `velora upgrade` upgrades apps a company already has. Add a new application (for example Velora Admin) to every company with:
  `sudo -u velora VELORA_WORKSPACE=/srv/velora/workspace /srv/velora/venv/bin/velora install-app velora_admin`
  It installs on every company, creates the tables, runs the app's install code and restarts. Then refresh the browser; the application appears in the App Hub.
- If the App Hub itself is missing, the Desk being served is an old one. Check `desk_path` in the workspace's common config (it overrides the packaged Desk) and the `VELORA_FRONTEND_DIST` variable.
