from .routes import subscription_bp
from .routes_webhook import webhook_bp


def register_subscription(app):
    # S4.0 -- audited but intentionally left unchanged. subscription_bp's
    # routes (modules/subscription/routes.py) already declare their full
    # paths in the decorator itself (e.g. @subscription_bp.get("/api/
    # subscription")), and this is the ONLY place this blueprint is
    # registered -- there is no duplicate registration to remove here.
    # The url_prefix below is redundant with those already-full paths,
    # so the only live path is the doubled one (e.g.
    # /api/subscription/api/subscription), not /api/subscription.
    # Removing the prefix (or the baked-in path) would RENAME the only
    # currently-live URL for this blueprint -- exactly the backward-
    # compatibility break S4.0 was told to avoid. Left intact and
    # documented per S4.0's own safety instruction.
    app.register_blueprint(subscription_bp, url_prefix="/api/subscription")
    app.register_blueprint(webhook_bp, url_prefix="")  # ✅ direct root path