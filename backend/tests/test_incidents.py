"""B4 · Human Review Center: cases open by themselves, fold repeats, review / escalate / act / resolve, safety-team only."""
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
        if "SADQ" in user:
            return {"category": "self_harm", "severity": "serious"}
        return {"category": "none", "severity": "none"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "i.db"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Teacher', 'History')")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    main.moderator.provider, main.moderator.llm = "llm", Clf()
    from app.services import admin, admin_auth
    admin.save_settings(main.db, {"safety": {"auto_block": False}})          # keep the student able to ask
    admin_auth.create_admin(main.db, "owner@x.in", "Passw0rd1", "Owner", "owner")
    admin_auth.create_admin(main.db, "tech@x.in", "Passw0rd1", "Tech", "technical")
    c = TestClient(main.app)
    c.main = main
    tok = lambda e: c.post("/admin/api/login", json={"email": e, "password": "Passw0rd1"}).json()["token"]  # noqa: E731
    c.admin, c.tech = {"Authorization": "Bearer " + tok("owner@x.in")}, {"Authorization": "Bearer " + tok("tech@x.in")}
    c.post("/auth/otp", json={"phone": "9876543210"}, headers={"X-Teacher-Id": "demo"})
    code = re.search(r"\d{6}", sent[-1]).group()
    t = c.post("/auth/verify", json={"phone": "9876543210", "code": code}, headers={"X-Teacher-Id": "demo"}).json()["token"]
    c.s = {"X-Teacher-Id": "demo", "Authorization": "Bearer " + t}
    main.db.execute("INSERT INTO subscriptions (student_id, plan_id, starts_at, ends_at) VALUES (1, 'p', 0, 9999999999)")
    return c


def ask(c, q):
    return c.post("/class/ask", json={"question": q}, headers=c.s).json()


def items(c, **params):
    return c.get("/admin/api/incidents", params=params, headers=c.admin).json()


def test_cases_open_by_themselves_most_urgent_first(client):
    ask(client, "Who was Akbar?")
    client.main.llm.replies = [{"query": "x"}, {"scope": "study", "answer": "BADOUT text", "follow_up": ""}]
    ask(client, "Tell me about Babur")                         # AI answer stopped → low
    ask(client, "WEAPONQ please")                              # harmful request → medium
    ask(client, "SADQ sab bekaar hai")                         # upset student → high, top of the list
    lst = items(client)
    assert [i["kind"] for i in lst["items"]] == ["care", "serious_request", "ai_stopped"]
    assert lst["items"][0]["severity"] == "high" and lst["high_open"] == 1 and lst["counts"]["open"] == 3
    assert lst["items"][0]["student_phone"] == "+91•••••210"


def test_repeats_fold_into_one_case(client):
    ask(client, "WEAPONQ one")
    ask(client, "WEAPONQ two")
    lst = items(client)
    assert lst["total"] == 1 and lst["items"][0]["events"] == 2


def test_review_escalate_act_resolve(client):
    ask(client, "Who was Akbar?")
    ask(client, "WEAPONQ please")
    iid = items(client)["items"][0]["id"]
    d = client.get(f"/admin/api/incidents/{iid}", headers=client.admin).json()
    assert d["status"] == "in_review" and d["assigned_to"] == "owner@x.in"     # opening it starts the review
    assert [m["question"] for m in d["conversation"]] == ["Who was Akbar?", "WEAPONQ please"]
    assert d["conversation"][-1]["flagged"]
    act = lambda **b: client.post(f"/admin/api/incidents/{iid}/act", json=b, headers=client.admin)  # noqa: E731
    assert act(action="escalate", note="needs safety head").json()["status"] == "escalated"
    assert act(action="stop_class").status_code == 200
    assert client.main.db.one("SELECT ended_at FROM class_sessions")["ended_at"] is not None
    assert act(action="pause_teacher", note="checking notes").status_code == 200
    assert client.post("/class/ask", json={"question": "q"}, headers=client.s).status_code == 503   # A4 switch on
    assert act(action="resolve", resolution="action_taken", note="").status_code == 400           # remarks required
    assert act(action="resolve", resolution="bogus", note="x").status_code == 400
    d = act(action="resolve", resolution="action_taken", note="Spoke to parent; teacher fixed notes").json()
    assert d["status"] == "resolved" and d["resolved_by"] == "owner@x.in"
    steps = [t["action"] for t in d["timeline"]]
    assert steps[:2] == ["opened", "started review"] and "escalated to safety team" in steps and steps[-1].startswith("resolved")
    assert items(client)["total"] == 0 and items(client, status="resolved")["total"] == 1
    assert act(action="reopen", note="parent called again").json()["status"] == "in_review"


def test_flag_by_code_and_ai_failure_counts_on_dashboard(client):
    a = ask(client, "Who was Akbar?")
    r = client.post("/admin/api/incidents/flag", json={"qa_id": a["qa_id"], "note": "Parent complaint about this answer"},
                    headers=client.admin)
    assert r.status_code == 200 and r.json()["kind"] == "report" and r.json()["flagged_by"] == "owner@x.in"
    iid = r.json()["id"]
    client.post(f"/admin/api/incidents/{iid}/act", headers=client.admin,
                json={"action": "resolve", "resolution": "ai_failure", "note": "Answer was not suitable"})
    d = client.get("/admin/api/safety-dashboard", headers=client.admin).json()
    assert d["ai"]["reported_failures"] == 1 and d["review"]["resolved"] == 1
    assert client.post("/admin/api/incidents/flag", json={"note": "x"}, headers=client.admin).status_code == 400


def test_only_the_safety_team_sees_conversations(client):
    ask(client, "WEAPONQ please")
    for path in ["/admin/api/incidents", "/admin/api/incidents/1", "/admin/api/students/1", "/admin/api/verify?q=x",
                 "/admin/api/students", "/admin/api/safety-events"]:
        assert client.get(path, headers=client.tech).status_code == 403, path
        assert client.get(path, headers=client.admin).status_code == 200, path
    assert client.get("/admin/api/safety-dashboard", headers=client.tech).status_code == 200   # numbers only: allowed
    log = client.get("/admin/api/audit", headers=client.admin).json()["items"]
    assert any(x["path"] == "/admin/api/incidents/1" and x["who"] == "owner@x.in" for x in log)   # every look is logged
