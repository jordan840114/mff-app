import os
import json

try:
    from pywebpush import webpush, WebPushException
    _WEBPUSH_AVAILABLE = True
except Exception as e:
    print(f"pywebpush not available: {e}")
    _WEBPUSH_AVAILABLE = False

_raw = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PRIVATE_KEY = _raw.replace("\\n", "\n") if _raw else None
VAPID_CLAIMS = {"sub": "mailto:" + os.environ.get("VAPID_EMAIL", "admin@mff.app")}


def send_push_to_all(db, PushSubscription, title, body):
    if not _WEBPUSH_AVAILABLE or not VAPID_PRIVATE_KEY:
        print(f"[通知] {title}: {body}")
        return

    subscriptions = PushSubscription.query.all()
    dead = []

    for sub in subscriptions:
        try:
            webpush(
                subscription_info=json.loads(sub.subscription_json),
                data=json.dumps({"title": title, "body": body}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
        except WebPushException as e:
            if e.response and e.response.status_code in (404, 410):
                dead.append(sub)
            else:
                print(f"推播失敗: {e}")
        except Exception as e:
            print(f"推播失敗: {e}")

    for sub in dead:
        db.session.delete(sub)
    if dead:
        db.session.commit()
