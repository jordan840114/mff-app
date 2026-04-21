import os
import json
from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from models import db, Flight, PushSubscription
from tracker import check_all_flights, fetch_cheapest_price
from notify import send_push_to_all
from datetime import datetime

app = Flask(__name__)

database_url = os.environ.get("DATABASE_URL", "sqlite:///mff.db")
# Render 的 PostgreSQL URL 以 postgres:// 開頭，SQLAlchemy 需要 postgresql://
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

with app.app_context():
    db.create_all()


def send_notification(title, body):
    with app.app_context():
        send_push_to_all(db, PushSubscription, title, body)


scheduler = BackgroundScheduler(timezone="Asia/Taipei")
scheduler.add_job(
    lambda: check_all_flights(app, db, Flight, send_notification),
    "interval",
    hours=6,
    next_run_time=None,
)
scheduler.start()


@app.route("/")
def index():
    return render_template("index.html", vapid_public_key=os.environ.get("VAPID_PUBLIC_KEY", ""))


@app.route("/api/flights", methods=["GET"])
def get_flights():
    flights = Flight.query.order_by(Flight.created_at.desc()).all()
    return jsonify([f.to_dict() for f in flights])


@app.route("/api/flights", methods=["POST"])
def add_flight():
    data = request.json
    required = ["origin", "destination", "departure_date", "target_price"]
    if not all(data.get(k) for k in required):
        return jsonify({"error": "缺少必要欄位"}), 400

    flight = Flight(
        origin=data["origin"].upper(),
        destination=data["destination"].upper(),
        departure_date=data["departure_date"],
        return_date=data.get("return_date"),
        target_price=int(data["target_price"]),
        currency=data.get("currency", "TWD"),
    )
    db.session.add(flight)
    db.session.commit()

    # 新增後立即查一次價格
    try:
        price = fetch_cheapest_price(
            flight.origin, flight.destination,
            flight.departure_date, flight.return_date, flight.currency
        )
        if price:
            flight.current_price = price
            flight.last_checked = datetime.utcnow()
            db.session.commit()
    except Exception:
        pass

    return jsonify(flight.to_dict()), 201


@app.route("/api/flights/<int:flight_id>", methods=["DELETE"])
def delete_flight(flight_id):
    flight = Flight.query.get_or_404(flight_id)
    db.session.delete(flight)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/flights/<int:flight_id>/check", methods=["POST"])
def check_flight(flight_id):
    flight = Flight.query.get_or_404(flight_id)
    price = fetch_cheapest_price(
        flight.origin, flight.destination,
        flight.departure_date, flight.return_date, flight.currency
    )
    if price is None:
        return jsonify({"error": "查詢失敗"}), 502

    flight.current_price = price
    flight.last_checked = datetime.utcnow()
    db.session.commit()
    return jsonify(flight.to_dict())


@app.route("/api/subscribe", methods=["POST"])
def subscribe():
    data = request.json
    endpoint = data.get("endpoint")
    if not endpoint:
        return jsonify({"error": "無效的訂閱"}), 400

    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if not sub:
        sub = PushSubscription(endpoint=endpoint, subscription_json=json.dumps(data))
        db.session.add(sub)
        db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/unsubscribe", methods=["POST"])
def unsubscribe():
    data = request.json
    endpoint = data.get("endpoint")
    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if sub:
        db.session.delete(sub)
        db.session.commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
