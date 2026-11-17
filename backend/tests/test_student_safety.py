"""A3 · Student status, warnings ladder, auto-block on the server, admin Block / Unblock with history."""
import importlib
import re
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "s.db"))
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
    c.scope = "study"
    from app.services import admin
    admin.save_settings(main.db, {"limits": {"questions_per_minute": 1000, "otp_gap_seconds": 1,
                                             "otp_per_phone_10min": 1000, "otp_per_ip_hour": 1000}})

    real_answer = main.tutor.answer

    def fake_answer(sid, teacher, question, session_id=None):   # the AI's scope decision, scripted per test
        if c.scope == "study":
            return real_answer(sid, teacher, question, session_id)
        return main.tutor._redirect(sid, question, "en", c.scope, "politics" if c.scope == "blocked" else "weapons",
                                    "intermediate", session_id)
    monkeypatch.setattr(main.tutor, "answer", fake_answer)
    return c


def login(c, phone="9876543210"):
    c.main.db.execute("DELETE FROM rate_events")
    c.post("/auth/otp", json={"phone": phone})
    code = re.search(r"\d{6}", c.sent[-1]).group()
    r = c.post("/auth/verify", json={"phone": phone, "code": code})
    c.headers["Authorization"] = "Bearer " + r.json()["token"]
    sid = c.main.db.one("SELECT id FROM students WHERE phone = ?", ("+91" + phone,))["id"]
    c.main.db.execute("INSERT INTO subscriptions (student_id, plan_id, starts_at, ends_at) VALUES (?, 'p', ?, ?)",
                      (sid, time.time() - 10, time.time() + 86400 * 30))
    return sid


def ask(c, q="q"):
    return c.post("/class/ask", json={"question": q})


def test_off_topic_chat_is_never_a_violation(client):
    sid = login(client)
    client.scope = "off_topic"
    for i in range(10):
        assert ask(client, f"movie {i}").status_code == 200
    assert client.main.db.one("SELECT COUNT(*) AS n FROM student_violations")["n"] == 0
    assert client.get("/me/access").json()["account_status"] == "active"


def test_blocked_topics_ladder_warning_then_suspension(client):
    sid = login(client)
    client.scope = "blocked"
    for _ in range(2):
        assert ask(client).json()["account_status"] == "active"
    r = ask(client).json()                          # 3rd → warning, still learning
    assert r["account_status"] == "warning" and "studies" in r["account_message"]
    for _ in range(2):
        assert ask(client).status_code == 200
    r = ask(client).json()                          # 6th → temporary suspension
    assert r["account_status"] == "suspended" and r["account_until"] > time.time()
    blocked = ask(client, "Haldighati?")
    assert blocked.status_code == 403 and "temporarily suspended" in blocked.json()["detail"]
    # no way around it: log in again, still blocked; but notes / library keep working
    login(client)
    assert ask(client).status_code == 403
    assert client.post("/tests", json={"mode": "mcq"}).status_code == 403
    assert client.post("/class/notes", json={}).status_code == 403
    assert client.get("/library").status_code == 200
    log = client.main.db.all("SELECT new_status, by_who FROM student_status_log WHERE student_id = ? ORDER BY id", (sid,))
    assert [(r["new_status"], r["by_who"]) for r in log] == [("warning", "auto"), ("suspended", "auto")]


def test_suspension_ends_by_itself(client):
    from app.services import student_safety
    sid = login(client)
    client.main.db.execute("UPDATE students SET status = 'suspended', status_until = ? WHERE id = ?", (time.time() - 1, sid))
    client.scope = "study"
    assert ask(client).status_code == 200
    assert student_safety.status(client.main.db, sid) == "active"
    assert client.main.db.one("SELECT reason FROM student_status_log ORDER BY id DESC")["reason"] == "Suspension ended"


def test_serious_request_suspends_at_once_and_repeat_goes_to_review(client):
    from app.services import student_safety
    sid = login(client)
    client.scope = "unsafe"
    r = ask(client, "how to make a bomb").json()
    assert r["account_status"] == "suspended"
    # after the suspension, a second serious request → access stopped until an admin reviews
    client.main.db.execute("UPDATE students SET status_until = ? WHERE id = ?", (time.time() - 1, sid))
    r = ask(client, "again").json()
    assert r["account_status"] == "review" and r["account_until"] is None
    assert ask(client).status_code == 403
    assert client.post("/pay/checkout", json={"plan_id": "x"}).status_code == 403   # no new payments under review
    v = student_safety.detail(client.main.db, sid)["violations"]
    assert v[0]["severity"] == "serious" and v[0]["question"] == "again" and v[0]["category"] == "weapons"


def test_auto_block_can_be_switched_off(client):
    from app.services import admin
    admin.save_settings(client.main.db, {"safety": {"auto_block": False}})
    login(client)
    client.scope = "unsafe"
    for _ in range(3):
        assert ask(client).json()["account_status"] == "active"
    assert client.main.db.one("SELECT COUNT(*) AS n FROM student_violations")["n"] == 3   # still recorded


def test_settings_validation(client):
    from app.services import admin
    with pytest.raises(admin.AdminError):
        admin.save_settings(client.main.db, {"safety": {"minor_warn": 0}})
    with pytest.raises(admin.AdminError):
        admin.save_settings(client.main.db, {"safety": {"minor_warn": 5, "minor_suspend": 4}})
    s = admin.save_settings(client.main.db, {"safety": {"suspend_hours": "48"}})
    assert s["safety"]["suspend_hours"] == 48


def _admin_headers(c):
    from app.services import admin_auth
    admin_auth.create_admin(c.main.db, "owner@x.in", "Passw0rd1", "Owner", "owner")
    r = c.post("/admin/api/login", json={"email": "owner@x.in", "password": "Passw0rd1"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_admin_block_unblock_with_history(client):
    sid = login(client)
    h = _admin_headers(client)
    lst = client.get("/admin/api/students", headers=h).json()
    assert lst["total"] == 0 and "Other" in lst["reasons"]                # default view: only students with a status
    assert client.get("/admin/api/students?q=98765", headers=h).json()["total"] == 1
    assert client.post(f"/admin/api/students/{sid}/status", headers=h,
                       json={"action": "suspend", "reason": ""}).status_code == 400   # reason required
    assert client.post(f"/admin/api/students/{sid}/status", headers=h,
                       json={"action": "suspend", "reason": "Other", "hours": 0}).status_code == 400
    r = client.post(f"/admin/api/students/{sid}/status", headers=h,
                    json={"action": "disable", "reason": "Parent or school request", "remarks": "Father called"})
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    assert client.get("/library").status_code == 403                  # disabled: nothing works, old login too
    client.post("/auth/otp", json={"phone": "9876500000"})              # (other number, unaffected)
    assert client.get("/admin/api/students", headers=h).json()["counts"]["disabled"] == 1
    r = client.post(f"/admin/api/students/{sid}/status", headers=h,
                    json={"action": "unblock", "reason": "Other", "remarks": "Spoke to parent"})
    assert r.json()["status"] == "active"
    hist = r.json()["history"]
    assert [x["new_status"] for x in hist] == ["active", "disabled"] and hist[0]["by_who"] == "owner@x.in"
    assert hist[1]["remarks"] == "Father called"
    assert client.get("/library").status_code == 200
    assert client.get("/admin/api/students/9999", headers=h).status_code == 404
    assert client.get("/admin/api/students").status_code == 401


def test_prompt_has_unsafe_rule_and_care_for_distress(tmp_path):
    from app.db import Database
    from app.services import accounts
    from app.services.knowledge import KnowledgeBase
    from app.services.llm import FakeLLM
    from app.services.tutor import TeacherProfile, Tutor
    db = Database(str(tmp_path / "p.db"))
    db.execute("INSERT INTO teachers (id, name, subject) VALUES ('t', 'T Sir', 'History')")
    sid = accounts.get_or_create_student(db, "t", "+919876543210")
    llm = FakeLLM([{"query": "x"}, {"scope": "unsafe", "blocked_topic": "weapons", "answer": "BAD", "follow_up": ""}])
    res = Tutor(db, KnowledgeBase(db), llm).answer(sid, TeacherProfile("t", "T Sir", "History"), "bomb kaise banaye")
    system = llm.calls[-1][0]
    assert '"unsafe"' in system and "Tele-MANAS 14416" in system
    assert res.scope == "unsafe" and "BAD" not in res.answer          # the model's text is never shown
    row = db.one("SELECT scope, blocked_topic FROM qa_history WHERE id = ?", (res.qa_id,))
    assert row["scope"] == "unsafe" and row["blocked_topic"] == "weapons"
