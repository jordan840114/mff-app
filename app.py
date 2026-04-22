import os
import json
import time
from flask import Flask, render_template, request, jsonify
from sqlalchemy import text, inspect as sa_inspect
from apscheduler.schedulers.background import BackgroundScheduler
from models import db, Flight, PushSubscription
from tracker import check_all_flights, fetch_cheapest_price
from notify import send_push_to_all
from datetime import datetime

app = Flask(__name__)

database_url = os.environ.get("DATABASE_URL", "sqlite:///mff.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
if "postgresql" in database_url:
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {"connect_timeout": 10},
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

db.init_app(app)

# 建立資料表，最多重試 3 次
_db_ready = False
for attempt in range(3):
    try:
        with app.app_context():
            db.create_all()
        _db_ready = True
        print(f"DB ready (attempt {attempt+1})")
        # ALTER TABLE migration：讓 target_price 可為 null（舊 DB 欄位可能有 NOT NULL）
        try:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE flights ALTER COLUMN target_price DROP NOT NULL"))
                conn.commit()
            print("Migration: target_price nullable OK")
        except Exception as me:
            print(f"Migration note: {me}")
        try:
            existing_cols = {c["name"] for c in sa_inspect(db.engine).get_columns("flights")}
            with db.engine.connect() as conn:
                for col, coltype in [("passengers", "INTEGER DEFAULT 1"), ("cabin_class", "INTEGER DEFAULT 1")]:
                    if col not in existing_cols:
                        conn.execute(text(f"ALTER TABLE flights ADD COLUMN {col} {coltype}"))
                        print(f"Migration: added {col}")
                    else:
                        print(f"Migration: {col} already exists")
                conn.commit()
        except Exception as me:
            print(f"Migration error (passengers/cabin_class): {me}")
        break
    except Exception as e:
        print(f"DB init attempt {attempt+1} failed: {e}")
        if attempt < 2:
            time.sleep(5)


def send_notification(title, body):
    with app.app_context():
        send_push_to_all(db, PushSubscription, title, body)


scheduler = BackgroundScheduler(timezone="Asia/Taipei", daemon=True)
scheduler.add_job(
    lambda: check_all_flights(app, db, Flight, send_notification),
    "interval",
    hours=6,
)
try:
    scheduler.start()
    print("Scheduler started")
except Exception as e:
    print(f"Scheduler start failed: {e}")


@app.route("/health")
def health():
    return {"status": "ok", "db_ready": _db_ready}


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
    required = ["origin", "destination", "departure_date"]
    if not all(data.get(k) for k in required):
        return jsonify({"error": "缺少必要欄位"}), 400

    tp = data.get("target_price")
    flight = Flight(
        origin=data["origin"].upper(),
        destination=data["destination"].upper(),
        departure_date=data["departure_date"],
        return_date=data.get("return_date") or None,
        target_price=int(tp) if tp else None,
        currency=data.get("currency", "TWD"),
        passengers=int(data.get("passengers") or 1),
        cabin_class=int(data.get("cabin_class") or 1),
    )
    db.session.add(flight)
    db.session.commit()

    try:
        price = fetch_cheapest_price(
            flight.origin, flight.destination,
            flight.departure_date, flight.return_date, flight.currency,
            flight.passengers or 1, flight.cabin_class or 1,
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
        flight.departure_date, flight.return_date, flight.currency,
        flight.passengers or 1, flight.cabin_class or 1,
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
