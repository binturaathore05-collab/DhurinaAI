"""A4 · Emergency kill switches: all AI chat, one teacher, one model, voice / photo; logged; restore needs a note."""
import importlib
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "k.db"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Teacher', 'History')")
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('other', 'Other Sir', 'Maths')")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    from app.services import admin_auth
    admin_auth.create_admin(main.db, "owner@x.in", "Passw0rd1", "Owner", "owner")
    c = TestClient(main.app)
    c.main, c.sent = main, sent
    tok = c.post("/admin/api/login", json={"email": "owner@x.in", "password": "Passw0rd1"}).json()["token"]
    c.admin = {"Authorization": "Bearer " + tok}
    return c


def student(c, teacher="demo", phone="9876543210"):
    h = {"X-Teacher-Id": teacher}
    c.post("/auth/otp", json={"phone": phone}, headers=h)
    code = re.search(r"\d{6}", c.sent[-1]).group()
    tok = c.post("/auth/verify", json={"phone": phone, "code": code}, headers=h).json()["token"]
    return {**h, "Authorization": "Bearer " + tok}


def switch(c, key, off, reason="test"):
    return c.post("/admin/api/emergency", headers=c.admin, json={"key": key, "off": off, "reason": reason})


def test_all_ai_off_stops_every_teacher_but_notes_and_library_work(client):
    a, b = student(client), student(client, "other", "9876500000")
    assert client.post("/class/ask", json={"question": "Who was Akbar?"}, headers=a).status_code == 200
    assert switch(client, "all_ai", True, "Bad answers going viral").status_code == 200
    for h in (a, b):
        r = client.post("/class/ask", json={"question": "Who was Babur?"}, headers=h)
        assert r.status_code == 503 and "short break" in r.json()["detail"]
        assert client.post("/tests", json={"mode": "mcq"}, headers=h).status_code == 503
        assert client.get("/library", headers=h).status_code == 200
        assert "short break" in client.get("/me/access", headers=h).json()["service_message"]
    assert client.get("/me/access", headers=a).json()["demo_questions_left"] == 2   # blocked tries cost nothing
    assert client.get("/teacher", headers={"X-Teacher-Id": "demo"}).json()["features"]["ai_chat"] is False
    assert switch(client, "all_ai", False, "Prompt fixed and tested").status_code == 200
    assert client.post("/class/ask", json={"question": "Who was Babur?"}, headers=a).status_code == 200
    assert client.get("/me/access", headers=a).json()["service_message"] is None


def test_one_teacher_off(client):
    a, b = student(client), student(client, "other", "9876500000")
    switch(client, "teacher:demo", True, "Wrong notes uploaded")
    assert client.post("/class/ask", json={"question": "q"}, headers=a).status_code == 503
    assert client.post("/class/ask", json={"question": "q"}, headers=b).status_code == 200


def test_model_off_moves_to_backup_or_pauses(client):
    from app.services import switches
    from app.services.llm import FakeLLM
    main_m, backup_m = FakeLLM([{"answer": "from main"}]), FakeLLM([{"answer": "from backup"}])
    r = switches.ModelRouter(client.main.db, [("gpt-main", main_m), ("gpt-backup", backup_m)])
    assert r.chat_json("s", "u")["answer"] == "from main"
    switches.set_switch(client.main.db, "model:gpt-main", True, "bad outputs", "owner@x.in")
    assert r.chat_json("s", "u")["answer"] == "from backup"
    switches.set_switch(client.main.db, "model:gpt-backup", True, "also bad", "owner@x.in")
    assert not r.available()
    with pytest.raises(switches.AIPaused):
        r.chat_json("s", "u")


def test_voice_and_photo_flags(client):
    switch(client, "voice", True, "Voice saying wrong words")
    f = client.get("/teacher", headers={"X-Teacher-Id": "demo"}).json()["features"]
    assert f == {"ai_chat": True, "voice": False, "photo": True}


def test_rules_reason_required_logged_and_admin_only(client):
    assert switch(client, "all_ai", True, "  ").status_code == 400                  # always say why
    assert switch(client, "teacher:nobody", True).status_code == 400
    assert switch(client, "something", True).status_code == 400
    switch(client, "all_ai", True, "Spike in unsafe answers")
    assert switch(client, "all_ai", True, "again").status_code == 400               # already off
    switch(client, "all_ai", False, "Checked 20 answers, all fine")
    log = client.get("/admin/api/emergency", headers=client.admin).json()["log"]
    assert [(x["off"], x["reason"], x["by_who"]) for x in log] == [
        (0, "Checked 20 answers, all fine", "owner@x.in"), (1, "Spike in unsafe answers", "owner@x.in")]
    assert log[0]["label"] == "AI chat for all teachers"
    assert client.post("/admin/api/emergency", json={"key": "all_ai", "off": True, "reason": "x"}).status_code == 401
    ov = client.get("/admin/api/emergency", headers=client.admin).json()
    assert {t["id"] for t in ov["teachers"]} == {"demo", "other"} and ov["any_off"] is False
