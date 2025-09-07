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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    language = db.Column(db.String(10), default="en")
    report_stage = db.Column(db.String(50), default="Pending")  # e.g., Pending, Generating, Ready
    pdf_url = db.Column(db.String(255))  
