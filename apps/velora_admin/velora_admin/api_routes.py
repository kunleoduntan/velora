"""Velora Admin HTTP route registration."""

def install_routes(app, scope, run):
    from velora_admin.administration import api
    api.install_routes(app, scope, run)
