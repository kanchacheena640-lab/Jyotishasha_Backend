# cron_app.py
from factory import create_app
from extensions import db

app = create_app()

# IMPORTANT: sirf db init, koi blueprint nahi
with app.app_context():
    pass
