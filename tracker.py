import os
import requests
from datetime import datetime


SERPAPI_KEY = os.environ.get("SERPAPI_KEY")


def fetch_cheapest_price(origin, destination, departure_date, return_date=None, currency="TWD"):
    if not SERPAPI_KEY:
        return None

    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": departure_date,
        "currency": currency,
        "hl": "zh-tw",
        "api_key": SERPAPI_KEY,
    }
    if return_date:
        params["return_date"] = return_date
        params["type"] = "1"  # round trip
    else:
        params["type"] = "2"  # one way

    try:
        resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # 從 best_flights 或 other_flights 取最低價
        all_flights = data.get("best_flights", []) + data.get("other_flights", [])
        if not all_flights:
            return None

        prices = [f["price"] for f in all_flights if f.get("price")]
        return min(prices) if prices else None

    except Exception as e:
        print(f"查價失敗: {e}")
        return None


def check_all_flights(app, db, Flight, send_notification_fn):
    with app.app_context():
        flights = Flight.query.all()
        for flight in flights:
            try:
                price = fetch_cheapest_price(
                    flight.origin,
                    flight.destination,
                    flight.departure_date,
                    flight.return_date,
                    flight.currency,
                )
                if price is None:
                    continue

                flight.current_price = price
                flight.last_checked = datetime.utcnow()
                db.session.commit()

                if price <= flight.target_price:
                    send_notification_fn(
                        title="MFF 低價警報！",
                        body=f"{flight.origin} → {flight.destination} 現在 {price} {flight.currency}，低於你的目標 {flight.target_price}！",
                    )
            except Exception as e:
                print(f"查價失敗 ({flight.origin}→{flight.destination}): {e}")
