from flask import Flask
import app_config
from extensions import db, jwt

def create_app():
    app = Flask(__name__)
    app.config.from_object(app_config)
    db.init_app(app)
    jwt.init_app(app)

    with app.app_context():
        db.create_all()

    return app
