from extensions import db

class DailyCounter(db.Model):
    __tablename__ = "daily_counter"

    id = db.Column(db.Integer, primary_key=True)
    counter = db.Column(db.Integer, nullable=False, default=0)
