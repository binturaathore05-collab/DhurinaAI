"""Parent dashboard: OTP login for a parent's number, the child's progress (never the child's words), consent and delete."""
import importlib
import json
import re
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

PARENT = "+919811100001"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    db = main.db
    db.execute("INSERT INTO teachers (id, name, app_name) VALUES ('demo', 'Demo Sir', 'Demo Sir AI')")
    sid = main.accounts.get_or_create_student(db, "demo", "+919876500001")
    db.execute("UPDATE students SET name = 'Riya', class_level = '8', is_adult = 0 WHERE id = ?", (sid,))
    main.consent.record(db, sid, "demo", PARENT, "1.2.3.4")
    db.execute("INSERT INTO qa_history (student_id, question, answer, origin, language, topic, scope) VALUES "
               "(?, 'my secret question about photosynthesis', 'Sir answer', 'general_ai', 'en', 'Photosynthesis', 'study')", (sid,))
    db.execute("INSERT INTO tests (student_id, teacher_id, mode, language, topics, questions, status, outcome, created_at) "
               "VALUES (?, 'demo', 'mcq', 'en', ?, '[]', 'done', ?, ?)",
               (sid, json.dumps(["Photosynthesis"]), json.dumps({"percent": 80, "score": 4, "total": 5}), time.time()))
    other = main.accounts.get_or_create_student(db, "demo", "+919876500002")   # someone else's child
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append((phone, msg))
    return TestClient(main.app), main, sid, other, sent


def login(c, sent, phone="9811100001"):
    assert c.post("/parent/api/otp", json={"phone": phone}).json()["sent"]
    code = re.search(r"\d{6}", sent[-1][1]).group()
    return c.post("/parent/api/verify", json={"phone": phone, "code": code})


def test_parent_sees_progress_not_words(setup):
    c, main, sid, other, sent = setup
    assert c.get("/parent").status_code == 200
    tok = login(c, sent).json()["token"]
    d = c.get("/parent/api/children", headers={"Authorization": "Bearer " + tok}).json()["children"]
    assert len(d) == 1 and d[0]["name"] == "Riya" and d[0]["consent"] == "given"
    assert d[0]["topics"][0]["topic"] == "Photosynthesis" and d[0]["tests"][0]["percent"] == 80
    assert d[0]["week"]["questions"] == 1 and len(d[0]["days"]) == 14
    assert "secret question" not in json.dumps(d) and "Sir answer" not in json.dumps(d)   # never the child's words
    assert main.db.one("SELECT action FROM parent_events")["action"] == "login"


def test_no_sms_for_numbers_that_are_not_a_parent(setup):
    c, main, sid, other, sent = setup
    r = c.post("/parent/api/otp", json={"phone": "9811199999"})
    assert r.json()["sent"] and not sent   # same reply, no SMS, no cost


def test_parent_can_only_touch_own_child(setup):
    c, main, sid, other, sent = setup
    h = {"Authorization": "Bearer " + login(c, sent).json()["token"]}
    assert c.post(f"/parent/api/children/{other}/withdraw", headers=h).status_code == 404
    assert c.post(f"/parent/api/children/{other}/delete", json={"confirm": "DELETE"}, headers=h).status_code == 404
    assert c.get("/parent/api/children", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_withdraw_then_delete(setup):
    c, main, sid, other, sent = setup
    h = {"Authorization": "Bearer " + login(c, sent).json()["token"]}
    d = c.post(f"/parent/api/children/{sid}/withdraw", headers=h).json()["children"]
    assert d[0]["consent"] == "withdrawn"
    assert main.db.one("SELECT revoked_by FROM parent_consents")["revoked_by"] == "parent"
    assert c.post(f"/parent/api/children/{sid}/delete", json={"confirm": "no"}, headers=h).status_code == 400
    assert c.post(f"/parent/api/children/{sid}/delete", json={"confirm": "DELETE"}, headers=h).json()["children"] == []
    assert main.db.one("SELECT phone FROM students WHERE id = ?", (sid,))["phone"].startswith("deleted:")


def test_student_profile_gives_the_parent_link(setup):
    c, main, sid, other, sent = setup
    tok = main.accounts.issue_token(sid, "demo", main.settings.jwt_secret, 1)
    me = c.get("/me", headers={"Authorization": "Bearer " + tok, "X-Teacher-Id": "demo"}).json()
    assert me["parent_url"].endswith("/parent")
