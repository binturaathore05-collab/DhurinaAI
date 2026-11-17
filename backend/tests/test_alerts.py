"""B7 · Alerts: raised at every trigger, never repeated within an hour, emailed without any child's words."""
import importlib
import re
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


class Clf:
    def chat_json(self, system, user):
        if "SADQ" in user:
            return {"category": "self_harm", "severity": "serious"}
        if "WEAPONQ" in user:
            return {"category": "weapons", "severity": "serious"}
        return {"category": "none", "severity": "none"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Teacher', 'History')")
    sent, mails = [], []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    main.moderator.provider, main.moderator.llm = "llm", Clf()
    from app.services import admin, admin_auth, alerts
    admin.save_settings(main.db, {"alerts": {"email_to": "safety@dhurina.in, owner@dhurina.in"},
                                  "safety": {"auto_block": False}})
    monkeypatch.setitem(alerts.mailer, "send", lambda to, subject, text: mails.append((to, subject, text)))
    monkeypatch.setitem(alerts.mailer, "base_url", "https://liveteach.example")
    admin_auth.create_admin(main.db, "owner@x.in", "Passw0rd1", "Owner", "owner")
    c = TestClient(main.app)
    c.main, c.mails = main, mails
    c.admin = {"Authorization": "Bearer " + c.post("/admin/api/login", json={"email": "owner@x.in", "password": "Passw0rd1"}).json()["token"]}
    c.post("/auth/otp", json={"phone": "9876543210"}, headers={"X-Teacher-Id": "demo"})
    code = re.search(r"\d{6}", sent[-1]).group()
    t = c.post("/auth/verify", json={"phone": "9876543210", "code": code}, headers={"X-Teacher-Id": "demo"}).json()["token"]
    c.s = {"X-Teacher-Id": "demo", "Authorization": "Bearer " + t}
    main.db.execute("INSERT INTO subscriptions (student_id, plan_id, starts_at, ends_at) VALUES (1, 'p', 0, 9999999999)")
    return c


def wait_mail(c, n):
    for _ in range(50):
        if len(c.mails) >= n:
            return
        time.sleep(0.05)


def kinds(c):
    return [a["kind"] for a in c.get("/admin/api/alerts", headers=c.admin).json()["items"]]


def test_upset_student_alert_is_critical_and_emailed_without_their_words(client):
    client.post("/class/ask", json={"question": "SADQ main bahut akela hoon"}, headers=client.s)
    a = client.get("/admin/api/alerts", headers=client.admin).json()
    assert a["critical"] == 1 and a["items"][0]["kind"] == "care" and a["items"][0]["link"].startswith("#/case/")
    wait_mail(client, 1)
    to, subject, text = client.mails[0]
    assert to == ["safety@dhurina.in", "owner@dhurina.in"] and subject.startswith("[LiveTeach CRITICAL]")
    assert "akela" not in text and "SADQ" not in text and "https://liveteach.example/admin#/case/" in text


def test_repeated_requests_auto_block_and_dedup(client):
    from app.services import admin
    for i in range(3):
        client.post("/class/ask", json={"question": f"WEAPONQ {i}"}, headers=client.s)
    assert kinds(client).count("repeated") == 1
    client.post("/class/ask", json={"question": "WEAPONQ 4"}, headers=client.s)
    assert kinds(client).count("repeated") == 1                       # not repeated within the hour
    admin.save_settings(client.main.db, {"safety": {"auto_block": True}})
    client.post("/class/ask", json={"question": "WEAPONQ 5"}, headers=client.s)
    assert "auto_block" in kinds(client)


def test_emergency_switch_alerts_everyone(client):
    client.post("/admin/api/emergency", headers=client.admin, json={"key": "all_ai", "off": True, "reason": "bad answers"})
    a = client.get("/admin/api/alerts", headers=client.admin).json()["items"][0]
    assert a["kind"] == "shutdown" and a["level"] == "critical" and "OFF" in a["title"] and "owner@x.in" in a["title"]


def test_pending_spike_and_check_down(client):
    from app.services import admin, alerts, incidents
    db = client.main.db
    iid = incidents.open_auto(db, "student_review", 1, "demo", "x", now=time.time() - 3 * 3600)
    now = time.time()
    for i in range(12):
        db.execute("INSERT INTO safety_events (at, stage, action, category) VALUES (?, 'output', 'replaced', 'violence')", (now - i,))
    for i in range(5):
        db.execute("INSERT INTO safety_events (at, stage, action, category) VALUES (?, 'input', 'retry', 'check_failed')", (now - i,))
    made = alerts.periodic(db, admin.get_settings(db), now)
    k = kinds(client)
    assert "pending" in k and "spike" in k and "check_down" in k and len(made) == 3
    assert alerts.periodic(db, admin.get_settings(db), now + 60) == []          # same alerts not repeated


def test_ack_and_settings(client):
    client.post("/admin/api/emergency", headers=client.admin, json={"key": "voice", "off": True, "reason": "t"})
    a = client.get("/admin/api/alerts", headers=client.admin).json()
    assert a["open"] == 1
    client.post("/admin/api/alerts/ack", headers=client.admin, json={"id": a["items"][0]["id"], "note": "known"})
    assert client.get("/admin/api/alerts", headers=client.admin).json()["open"] == 0
    old = client.get("/admin/api/alerts?all=true", headers=client.admin).json()["items"][0]
    assert old["ack_by"] == "owner@x.in" and old["ack_note"] == "known"
    from app.services import admin
    with pytest.raises(admin.AdminError):
        admin.save_settings(client.main.db, {"alerts": {"email_to": "not-an-email"}})
    with pytest.raises(admin.AdminError):
        admin.save_settings(client.main.db, {"alerts": {"email_level": "sometimes"}})
