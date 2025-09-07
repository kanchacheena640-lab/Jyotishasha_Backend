from .routes import subscription_bp
from .routes_webhook import webhook_bp


def register_subscription(app):
    app.register_blueprint(subscription_bp, url_prefix="/api/subscription")
    app.register_blueprint(webhook_bp, url_prefix="")  # ✅ direct root path