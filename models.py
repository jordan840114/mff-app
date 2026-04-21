from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Flight(db.Model):
    __tablename__ = "flights"
    id = db.Column(db.Integer, primary_key=True)
    origin = db.Column(db.String(3), nullable=False)
    destination = db.Column(db.String(3), nullable=False)
    departure_date = db.Column(db.String(10), nullable=False)
    return_date = db.Column(db.String(10))
    target_price = db.Column(db.Integer, nullable=True)
    current_price = db.Column(db.Integer)
    currency = db.Column(db.String(3), default="TWD")
    last_checked = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "origin": self.origin,
            "destination": self.destination,
            "departure_date": self.departure_date,
            "return_date": self.return_date,
            "target_price": self.target_price,
            "current_price": self.current_price,
            "currency": self.currency,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
        }


class PushSubscription(db.Model):
    __tablename__ = "push_subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    endpoint = db.Column(db.Text, unique=True, nullable=False)
    subscription_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
