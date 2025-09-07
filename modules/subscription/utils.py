from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt_identity
from modules.subscription.models import Subscription
from datetime import datetime

def subscription_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = get_jwt_identity()

        subscription = Subscription.query.filter_by(user_id=user_id).first()
        if not subscription or subscription.status != "active" or subscription.end_at < datetime.utcnow():
            return jsonify({"error": "Subscription inactive or expired"}), 403

        return fn(*args, **kwargs)
    return wrapper
