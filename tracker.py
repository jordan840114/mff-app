import os
import requests
from datetime import datetime


SERPAPI_KEY = os.environ.get("SERPAPI_KEY")

# 城市任選代碼 → 展開為各機場（供最低價比較）
CITY_AIRPORTS = {
    'TYO': ['NRT', 'HND'],
    'OSA': ['KIX', 'ITM'],
    'SEL': ['ICN', 'GMP'],
    'SHA': ['PVG', 'SHA'],
    'BJS': ['PEK', 'PKX'],
    'LON': ['LHR', 'LGW'],
    'NYC': ['JFK', 'LGA', 'EWR'],
    'BKK': ['BKK', 'DMK'],  # Suvarnabhumi + Don Mueang（廉航）
    'PAR': ['CDG', 'ORY'],
    'KUL': ['KUL'],
}


def _fetch_one(origin, destination, departure_date, return_date, currency, adults=1, travel_class=1):
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": departure_date,
        "currency": currency,
        "hl": "zh-tw",
        "adults": adults,
        "travel_class": travel_class,
        "api_key": SERPAPI_KEY,
    }
    if return_date:
        params["return_date"] = return_date
        params["type"] = "1"
    else:
        params["type"] = "2"

    resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    all_flights = data.get("best_flights", []) + data.get("other_flights", [])
    prices = [f["price"] for f in all_flights if f.get("price")]
    return min(prices) if prices else None


def fetch_price_breakdown(origin, destination, departure_date, return_date=None, currency="TWD", adults=1, travel_class=1):
    """Returns (min_price, breakdown_list) where breakdown is [{o, d, price}, ...]."""
    if not SERPAPI_KEY:
        return None, []

    origins = CITY_AIRPORTS.get(origin.upper(), [origin.upper()])
    dests   = CITY_AIRPORTS.get(destination.upper(), [destination.upper()])

    min_price = None
    breakdown = []
    for o in origins:
        for d in dests:
            try:
                p = _fetch_one(o, d, departure_date, return_date, currency, adults, travel_class)
                if p is not None:
                    breakdown.append({"o": o, "d": d, "price": p})
                    if min_price is None or p < min_price:
                        min_price = p
            except Exception as e:
                print(f"查價失敗 ({o}→{d}): {e}")
    return min_price, breakdown


def fetch_cheapest_price(origin, destination, departure_date, return_date=None, currency="TWD", adults=1, travel_class=1):
    price, _ = fetch_price_breakdown(origin, destination, departure_date, return_date, currency, adults, travel_class)
    return price


def check_all_flights(app, db, Flight, send_notification_fn):
    import json
    with app.app_context():
        flights = Flight.query.all()
        for flight in flights:
            try:
                price, breakdown = fetch_price_breakdown(
                    flight.origin,
                    flight.destination,
                    flight.departure_date,
                    flight.return_date,
                    flight.currency,
                    getattr(flight, 'passengers', 1) or 1,
                    getattr(flight, 'cabin_class', 1) or 1,
                )
                if price is None:
                    continue

                old_price = flight.current_price
                flight.current_price = price
                flight.price_breakdown = json.dumps(breakdown) if breakdown else None
                flight.last_checked = datetime.utcnow()
                db.session.commit()

                # 達到目標價
                if flight.target_price is not None and price <= flight.target_price:
                    send_notification_fn(
                        title="MFF 低價警報！",
                        body=f"{flight.origin} → {flight.destination} 現在 {price} {flight.currency}，低於目標 {flight.target_price}！",
                    )
                # 較上次大幅下降（≥8% 或 ≥800 TWD）
                elif old_price and price < old_price:
                    drop = old_price - price
                    drop_pct = drop / old_price
                    if drop_pct >= 0.08 or drop >= 800:
                        send_notification_fn(
                            title="MFF 價格下降",
                            body=f"{flight.origin} → {flight.destination} 降了 {drop:,} {flight.currency}，現在 {price:,}！",
                        )
            except Exception as e:
                print(f"查價失敗 ({flight.origin}→{flight.destination}): {e}")
