from extensions import db
from datetime import date

class DailyPersonalizedCache(db.Model):
    __tablename__ = "daily_personalized_cache"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, nullable=False)   # backend_user_id
    profile_id = db.Column(db.Integer, nullable=False)  # backendProfileId
    date = db.Column(db.Date, nullable=False)  # will always be today

    planet = db.Column(db.String(20), nullable=False)

    aspect_line_en = db.Column(db.Text, nullable=False)
    aspect_line_hi = db.Column(db.Text, nullable=False)

    remedy_en = db.Column(db.Text, nullable=False)
    remedy_hi = db.Column(db.Text, nullable=False)
