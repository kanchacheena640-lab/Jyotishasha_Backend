from flask import Flask
from dotenv import load_dotenv
import os
import app_config
from extensions import db, jwt, init_firebase   # 🔥 ADD THIS

load_dotenv()

def create_app():
    app = Flask(__name__)

    app.config.from_object(app_config)

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    jwt.init_app(app)

    init_firebase()   # 🔥 THIS LINE IS THE FIX

    with app.app_context():
        db.create_all()

    return app