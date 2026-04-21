import os
import requests
from datetime import datetime, timedelta


AMADEUS_API_KEY = os.environ.get("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.environ.get("AMADEUS_API_SECRET")
_token_cache = {"token": None, "expires_at": None}


def get_amadeus_token():
    now = datetime.utcnow()
    if _token_cache["token"] and _token_cache["expires_at"] > now:
        return _token_cache["token"]

    resp = requests.post(
        "https://test.api.amadeus.com/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": AMADEUS_API_KEY,
            "client_secret": AMADEUS_API_SECRET,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + timedelta(seconds=data["expires_in"] - 60)
    return _token_cache["token"]


def fetch_cheapest_price(origin, destination, departure_date, return_date=None, currency="TWD"):
    if not AMADEUS_API_KEY:
        return None

    token = get_amadeus_token()
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": departure_date,
        "adults": 1,
        "max": 1,
        "currencyCode": currency,
    }
    if return_date:
        params["returnDate"] = return_date

    resp = requests.get(
        "https://test.api.amadeus.com/v2/shopping/flight-offers",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )
    if resp.status_code != 200:
        return None

    data = resp.json()
    offers = data.get("data", [])
    if not offers:
        return None

    price = offers[0]["price"]["grandTotal"]
    return int(float(price))


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
