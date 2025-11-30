# modules/models_free_daily.py

"""
Tracks 1 Free Question Per Day for each user.

Rules:
- Each user gets 1 free question per calendar day (IST).
- When user takes their free question, we store today's date.
- If stored date == today's date → no more free question.
- Next day → auto-eligible again.
"""

from datetime import datetime, date
from extensions import db


class FreeDailyQuestion(db.Model):
    __tablename__ = "free_daily_questions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)

    # YYYY-MM-DD string (easy to compare)
    last_used_date = db.Column(db.String(10), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def used_today(self) -> bool:
        """Check if user already used free question today."""
        today = date.today().strftime("%Y-%m-%d")
        return self.last_used_date == today

    def mark_used(self):
        """Mark that user used today's free question."""
        today = date.today().strftime("%Y-%m-%d")
        self.last_used_date = today

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "last_used_date": self.last_used_date,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<FreeDaily user={self.user_id} last_used={self.last_used_date}>"
