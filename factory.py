from flask import Flask
from dotenv import load_dotenv
import os
import app_config
from extensions import db, jwt

load_dotenv()

def create_app():
    app = Flask(__name__)

    app.config.from_object(app_config)

    # 🔥 FORCE SET (ye missing tha)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    jwt.init_app(app)

    with app.app_context():
        db.create_all()

    return app