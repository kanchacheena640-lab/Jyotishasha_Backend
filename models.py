from extensions import db
from datetime import datetime

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    product = db.Column(db.String(100), nullable=False)
    dob = db.Column(db.String(20))
    tob = db.Column(db.String(20))
    pob = db.Column(db.String(100))
    status = db.Column(db.String(20), default="PENDING")
    created_at = db.Column(db.DateTime, default=datetime.now)
    language = db.Column(db.String(10), default="en")
    report_stage = db.Column(db.String(50), default="Pending")  # e.g., Pending, Generating, Ready
    pdf_url = db.Column(db.String(255))  
    latitude = db.Column(db.String)
    longitude = db.Column(db.String)
    partner_payload = db.Column(db.JSON, nullable=True)

class AstroEvent(db.Model):
    __tablename__ = "astro_events"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    date = db.Column(db.Date, nullable=False)
    type = db.Column(db.Text)
    priority = db.Column(db.Integer, default=1)
    notify_before_days = db.Column(db.Integer, default=0)
    notify_same_day = db.Column(db.Boolean, default=True)
    notify_time = db.Column(db.Time)
    meta = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.now)