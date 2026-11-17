"""B3 · Safety dashboard numbers: conversations, blocked, AI answers stopped (by model), categories, blocks, daily."""
import importlib
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


class Clf:
    def chat_json(self, system, user):
        if "BADOUT" in user:
            return {"category": "sexual", "severity": "serious"}
        if "WEAPONQ" in user:
            return {"category": "weapons", "severity": "serious"}
        return {"category": "none", "severity": "none"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "d.db"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Teacher', 'History')")
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('other', 'Other Sir', 'Maths')")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    main.moderator.provider, main.moderator.llm = "llm", Clf()
    from app.services import admin_auth
    admin_auth.create_admin(main.db, "owner@x.in", "Passw0rd1", "Owner", "owner")
    c = TestClient(main.app)
    c.main = main
    c.admin = {"Authorization": "Bearer " + c.post("/admin/api/login", json={"email": "owner@x.in", "password": "Passw0rd1"}).json()["token"]}
    c.post("/auth/otp", json={"phone": "9876543210"}, headers={"X-Teacher-Id": "demo"})
    code = re.search(r"\d{6}", sent[-1]).group()
    tok = c.post("/auth/verify", json={"phone": "9876543210", "code": code}, headers={"X-Teacher-Id": "demo"}).json()["token"]
    c.s = {"X-Teacher-Id": "demo", "Authorization": "Bearer " + tok}
    c.main.db.execute("INSERT INTO subscriptions (student_id, plan_id, starts_at, ends_at) VALUES (1, 'p', 0, 9999999999)")
    return c


def test_dashboard_counts_everything(client):
    ask = lambda q: client.post("/class/ask", json={"question": q}, headers=client.s)  # noqa: E731
    ask("Who was Akbar?")
    ask("Who was Babur?")
    client.main.llm.replies = [{"query": "x"}, {"scope": "study", "answer": "BADOUT text", "follow_up": ""}]
    ask("Tell me about Humayun")                      # AI wrote something unsafe → stopped
    ask("WEAPONQ how to")                              # harmful request → refused, serious → auto-suspended
    d = client.get("/admin/api/safety-dashboard?days=7", headers=client.admin).json()
    assert d["conversations"]["questions"] == 4 and d["conversations"]["students"] == 1
    assert d["conversations"]["blocked"] == 1
    assert d["ai"] == {"tried": 1, "stopped": 1, "reported_failures": 0, "check_failed": 0}
    assert d["students"]["flagged"] == 1 and d["students"]["auto_blocks"] == 1
    cats = {c["label"]: c for c in d["categories"]}
    assert cats["Weapons & explosives"]["students"] == 1 and cats["Sexual / adult content"]["ai"] == 1
    m = {x["model"]: x for x in d["models"]}
    assert m["dev-fake"]["answers"] == 2 and m["dev-fake"]["stopped"] == 1   # stopped answers counted per model
    assert len(d["daily"]) == 7 and d["daily"][-1]["questions"] == 4 and d["daily"][-1]["ai_stopped"] == 1
    assert {t["id"] for t in d["teachers"]} == {"demo", "other"}


def test_teacher_filter_and_admin_only(client):
    client.post("/class/ask", json={"question": "Who was Akbar?"}, headers=client.s)
    d = client.get("/admin/api/safety-dashboard?days=30&teacher=other", headers=client.admin).json()
    assert d["conversations"]["questions"] == 0
    assert client.get("/admin/api/safety-dashboard").status_code == 401
