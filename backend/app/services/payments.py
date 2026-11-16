"""Razorpay payments with automatic commission split (Razorpay Route).

The teacher's Razorpay account receives the payment; on each order a Route transfer sends the
platform commission (default 20%) to Durina's linked account automatically.
A subscription is activated only after the payment signature (or webhook) is verified, and only once.
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.request

from ..db import Database


def commission_paise(amount_paise: int, percent: float) -> int:
    return int(round(amount_paise * percent / 100))


def build_order_payload(amount_paise: int, receipt: str, linked_account: str, percent: float,
                        notes: dict | None = None) -> dict:
    payload = {"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes or {}}
    if linked_account and percent > 0:
        payload["transfers"] = [{
            "account": linked_account,
            "amount": commission_paise(amount_paise, percent),
            "currency": "INR",
            "notes": {"purpose": "platform commission"},
            "on_hold": 0,
        }]
    return payload


def create_razorpay_order(key_id: str, key_secret: str, payload: dict) -> dict:
    auth = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
    req = urllib.request.Request("https://api.razorpay.com/v1/orders", data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def verify_payment_signature(order_id: str, payment_id: str, signature: str, key_secret: str) -> bool:
    """Checkout returns razorpay_signature = HMAC_SHA256(order_id|payment_id, key_secret)."""
    expected = hmac.new(key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(raw_body: bytes, signature: str, webhook_secret: str) -> bool:
    expected = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def start_checkout(db: Database, student_id: int, plan_id: str, settings, order_creator=create_razorpay_order,
                   key_id: str | None = None, key_secret: str | None = None) -> dict:
    plan = db.one("SELECT * FROM plans WHERE id = ? AND active = 1", (plan_id,))
    if plan is None:
        raise KeyError(plan_id)
    receipt = f"s{student_id}-{plan_id}-{int(time.time())}"
    payload = build_order_payload(plan["amount_paise"], receipt, settings.platform_linked_account,
                                  settings.platform_commission_percent,
                                  {"student_id": str(student_id), "plan_id": plan_id})
    key_id = key_id or settings.razorpay_key_id
    order = order_creator(key_id, key_secret or settings.razorpay_key_secret, payload)
    db.execute("INSERT INTO payments (student_id, plan_id, razorpay_order_id, amount_paise) VALUES (?, ?, ?, ?)",
               (student_id, plan_id, order["id"], plan["amount_paise"]))
    # Everything the app needs to open Razorpay Checkout
    return {"key_id": key_id, "order_id": order["id"], "amount": plan["amount_paise"], "currency": "INR",
            "plan_name": plan["name"]}


def mark_paid(db: Database, order_id: str, payment_id: str, now: float | None = None) -> dict:
    """Record a verified payment and activate (or extend) the subscription. Safe to call twice."""
    now = now or time.time()
    pay = db.one("SELECT * FROM payments WHERE razorpay_order_id = ?", (order_id,))
    if pay is None:
        raise KeyError(order_id)
    if pay["status"] != "paid":
        plan = db.one("SELECT * FROM plans WHERE id = ?", (pay["plan_id"],))
        current = db.one("SELECT MAX(ends_at) AS e FROM subscriptions WHERE student_id = ?", (pay["student_id"],))
        start = max(now, current["e"] or 0)
        db.execute("UPDATE payments SET status = 'paid', razorpay_payment_id = ? WHERE id = ? AND status != 'paid'",
                   (payment_id, pay["id"]))
        db.execute("INSERT INTO subscriptions (student_id, plan_id, starts_at, ends_at, payment_id) "
                   "VALUES (?, ?, ?, ?, ?)",
                   (pay["student_id"], plan["id"], start, start + plan["duration_days"] * 86400, pay["id"]))
    sub = db.one("SELECT s.*, p.name AS plan_name FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                 "WHERE s.payment_id = ?", (pay["id"],))
    return {"plan": sub["plan_name"], "amount_paise": pay["amount_paise"], "valid_till": sub["ends_at"],
            "payment_id": payment_id}
