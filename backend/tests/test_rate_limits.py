"""A6 · Rate limits: questions per minute / day, OTP sends per phone / device / IP, wrong-code lock."""
import importlib
import re
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "rl.db"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Teacher', 'History')")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    c = TestClient(main.app)
    c.headers["X-Teacher-Id"] = "demo"
    c.sent, c.main = sent, main
    return c


def set_limits(c, **values):
    from app.services import admin
    admin.save_settings(c.main.db, {"limits": values})


def login(c, phone="9876543210"):
    assert c.post("/auth/otp", json={"phone": phone}).status_code == 200
    code = re.search(r"\d{6}", c.sent[-1]).group()
    r = c.post("/auth/verify", json={"phone": phone, "code": code})
    c.headers["Authorization"] = "Bearer " + r.json()["token"]
    return r.json()


def subscribe(c):
    sid = c.main.db.one("SELECT id FROM students")["id"]
    c.main.db.execute("INSERT INTO subscriptions (student_id, plan_id, starts_at, ends_at) VALUES (?, 'p', ?, ?)",
                      (sid, time.time() - 10, time.time() + 86400 * 30))


def test_questions_per_minute(client):
    login(client)
    subscribe(client)
    set_limits(client, questions_per_minute=3)
    for i in range(3):
        assert client.post("/class/ask", json={"question": f"Q{i}"}).status_code == 200
    r = client.post("/class/ask", json={"question": "Q4"})
    assert r.status_code == 429 and "fast" in r.json()["detail"] and int(r.headers["Retry-After"]) > 0
    # a blocked question does not use up a demo / plan question and is not stored
    assert client.main.db.one("SELECT COUNT(*) AS n FROM qa_history")["n"] == 3


def test_questions_per_day_and_window_moves(client):
    from app.services import limits
    login(client)
    subscribe(client)
    set_limits(client, questions_per_minute=100, questions_per_day=2)
    sid = client.main.db.one("SELECT id FROM students")["id"]
    old = time.time() - 86400 - 5   # yesterday's question no longer counts
    limits.record(client.main.db, f"ask:student:{sid}", now=old)
    assert client.post("/class/ask", json={"question": "a"}).status_code == 200
    assert client.post("/class/ask", json={"question": "b"}).status_code == 200
    r = client.post("/class/ask", json={"question": "c"})
    assert r.status_code == 429 and "today" in r.json()["detail"]


def test_tests_and_notes_count_but_mcq_answers_do_not(client):
    login(client)
    subscribe(client)
    client.post("/class/ask", json={"question": "Who was Akbar?"})
    set_limits(client, questions_per_minute=2)
    client.main.llm.replies = [{"questions": [{"q": f"Q{i}", "options": ["r", "w1", "w2", "w3"], "answer": 0,
                                               "explain": "", "topic": "Akbar"} for i in range(10)]}]
    test = client.post("/tests", json={"mode": "mcq"}).json()          # 2nd AI action this minute
    for _ in range(4):   # MCQ is checked without AI → never limited
        assert client.post(f"/tests/{test['id']}/answer", json={"answer": "A"}).status_code == 200
    assert client.post("/class/notes", json={}).status_code == 429


def test_otp_gap_and_per_phone(client):
    set_limits(client, otp_gap_seconds=1, otp_per_phone_10min=2)
    assert client.post("/auth/otp", json={"phone": "9876543210"}).status_code == 200
    r = client.post("/auth/otp", json={"phone": "+91 98765 43210"})   # same number, other spelling
    assert r.status_code == 429 and "just sent" in r.json()["detail"]
    time.sleep(1.1)
    assert client.post("/auth/otp", json={"phone": "9876543210"}).status_code == 200
    time.sleep(1.1)
    r = client.post("/auth/otp", json={"phone": "9876543210"})
    assert r.status_code == 429 and "Too many code requests" in r.json()["detail"]
    assert len(client.sent) == 2   # no SMS was sent for the blocked requests
    # a different number is not affected
    assert client.post("/auth/otp", json={"phone": "9876500000"}).status_code == 200


def test_otp_per_device_and_ip(client):
    set_limits(client, otp_per_device_day=2, otp_per_ip_hour=3)
    dev = {"X-Device-Id": "phone-abc"}
    assert client.post("/auth/otp", json={"phone": "9000000001"}, headers=dev).status_code == 200
    assert client.post("/auth/otp", json={"phone": "9000000002"}, headers=dev).status_code == 200
    assert client.post("/auth/otp", json={"phone": "9000000003"}, headers=dev).status_code == 429
    # another device, same IP: the IP limit (3 counted sends) stops it
    assert client.post("/auth/otp", json={"phone": "9000000004"}, headers={"X-Device-Id": "x"}).status_code == 200
    assert client.post("/auth/otp", json={"phone": "9000000005"}, headers={"X-Device-Id": "y"}).status_code == 429


def test_wrong_codes_lock_the_number(client):
    set_limits(client, otp_wrong_per_phone_day=3, otp_gap_seconds=1)
    client.post("/auth/otp", json={"phone": "9876543210"})
    for _ in range(3):
        assert client.post("/auth/verify", json={"phone": "9876543210", "code": "000000"}).status_code == 400
    code = re.search(r"\d{6}", client.sent[-1]).group()
    r = client.post("/auth/verify", json={"phone": "9876543210", "code": code})   # even the right code
    assert r.status_code == 429 and "wrong codes" in r.json()["detail"]
    time.sleep(1.1)
    assert client.post("/auth/otp", json={"phone": "9876543210"}).status_code == 429   # no new codes either


def test_admin_limits_validation(client):
    from app.services import admin
    with pytest.raises(admin.AdminError):
        admin.save_settings(client.main.db, {"limits": {"questions_per_day": 0}})
    with pytest.raises(admin.AdminError):
        admin.save_settings(client.main.db, {"limits": {"questions_per_day": "abc"}})
    s = admin.save_settings(client.main.db, {"limits": {"questions_per_day": "120", "unknown": 5}})
    assert s["limits"]["questions_per_day"] == 120 and "unknown" not in s["limits"]
