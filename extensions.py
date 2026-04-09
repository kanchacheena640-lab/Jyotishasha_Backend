from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager

import firebase_admin
from firebase_admin import credentials
import os
import json

db = SQLAlchemy(engine_options={
    "pool_pre_ping": True,
    "pool_recycle": 300
})
jwt = JWTManager()

# -------------------------------------------------
# 🔥 Firebase Admin Initialization (ONCE)
# -------------------------------------------------
if not firebase_admin._apps:
    # Render me JSON string env me hota hai
    firebase_json = os.environ.get("FCM_SERVICE_ACCOUNT_JSON")

    if firebase_json:
        cred = credentials.Certificate(json.loads(firebase_json))
        firebase_admin.initialize_app(cred)
    else:
        print("⚠️ FCM not initialized (env missing)")
