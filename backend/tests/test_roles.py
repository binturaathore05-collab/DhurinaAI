"""B5 · Team & roles: each role reaches only its own pages (checked on the server), team management by the Super Admin,
one-time passwords that must be changed, switching people off."""
import importlib
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Teacher', 'History')")
    from app.services import admin_auth
    admin_auth.create_admin(main.db, "owner@x.in", "Passw0rd1", "Owner", "owner")
    c = TestClient(main.app)
    c.main = main
    c.owner = login(c, "owner@x.in", "Passw0rd1")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    c.post("/auth/otp", json={"phone": "9876543210"}, headers={"X-Teacher-Id": "demo"})
    code = re.search(r"\d{6}", sent[-1]).group()
    c.post("/auth/verify", json={"phone": "9876543210", "code": code}, headers={"X-Teacher-Id": "demo"})
    main.db.execute("INSERT INTO student_violations (student_id, teacher_id, severity, category, question, at) "
                    "VALUES (1, 'demo', 'serious', 'weapons', 'secret words of the student', 1)")
    return c


def login(c, email, pw):
    r = c.post("/admin/api/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def member(c, role):
    """Super Admin adds a member; the member logs in with the one-time password and sets their own."""
    r = c.post("/admin/api/team", json={"email": f"{role}@x.in", "name": role.title(), "role": role}, headers=c.owner)
    assert r.status_code == 200, r.text
    tmp = r.json()["temp_password"]
    h = login(c, f"{role}@x.in", tmp)
    assert c.get("/admin/api/settings", headers=h).status_code == 403          # must set own password first
    assert c.get("/admin/api/me", headers=h).json()["must_change"] is True
    assert c.post("/admin/api/password", json={"current_password": tmp, "new_password": tmp}, headers=h).status_code == 400
    assert c.post("/admin/api/password", json={"current_password": tmp, "new_password": "Mine2026x"}, headers=h).status_code == 200
    return login(c, f"{role}@x.in", "Mine2026x")


ALLOWED = {   # GET page → roles that may open it
    "/admin/api/overview": {"owner", "technical", "support", "auditor"},
    "/admin/api/reports?date_from=2026-11-01&date_to=2026-11-17": {"owner", "auditor"},
    "/admin/api/settings": {"owner", "safety", "technical", "auditor"},
    "/admin/api/students": {"owner", "safety", "support"},
    "/admin/api/incidents": {"owner", "safety"},
    "/admin/api/verify?q=x": {"owner", "safety"},
    "/admin/api/emergency": {"owner", "safety", "technical", "auditor"},
    "/admin/api/audit": {"owner", "safety", "auditor"},
    "/admin/api/safety-dashboard": {"owner", "safety", "support", "technical", "auditor"},
    "/admin/api/team": {"owner"},
}


def test_each_role_reaches_only_its_pages(client):
    heads = {"owner": client.owner, **{r: member(client, r) for r in ["safety", "support", "technical", "auditor"]}}
    for path, ok in ALLOWED.items():
        for role, h in heads.items():
            code = client.get(path, headers=h).status_code
            assert (code == 200) == (role in ok), (path, role, code)


def test_actions_need_the_right_role(client):
    sup, aud, tech, saf = (member(client, r) for r in ["support", "auditor", "technical", "safety"])
    block = lambda h: client.post("/admin/api/students/1/status", headers=h, json={"action": "warn", "reason": "Other"})  # noqa: E731
    assert block(sup).status_code == 403 and block(aud).status_code == 403 and block(saf).status_code == 200
    em = lambda h: client.post("/admin/api/emergency", headers=h, json={"key": "voice", "off": True, "reason": "t"})  # noqa: E731
    assert em(aud).status_code == 403 and em(tech).status_code == 200
    # support sees the student's account but not what they wrote
    d = client.get("/admin/api/students/1", headers=sup).json()
    assert d["violations"][0]["question"].startswith("(hidden") and d["can"] == {"block": False, "consent": True, "evidence": False, "delete": True}
    assert client.get("/admin/api/students/1", headers=saf).json()["violations"][0]["question"] == "secret words of the student"
    # settings: safety admin may change safety sections only; auditor nothing
    assert client.put("/admin/api/settings", headers=saf, json={"safety": {"suspend_hours": 48}}).status_code == 200
    assert client.put("/admin/api/settings", headers=saf, json={"company": {"name": "X"}}).status_code == 403
    assert client.put("/admin/api/settings", headers=aud, json={"safety": {"suspend_hours": 12}}).status_code == 403
    # the whole form with unchanged money settings is fine for the safety admin
    full = client.get("/admin/api/settings", headers=saf).json()
    full["limits"]["questions_per_day"] = 400
    assert client.put("/admin/api/settings", headers=saf, json=full).status_code == 200
    assert client.post("/admin/api/teachers", headers=sup, json={"id": "t2", "name": "T"}).status_code == 403


def test_team_rules(client):
    r = client.post("/admin/api/team", json={"email": "owner@x.in", "role": "support"}, headers=client.owner)
    assert r.status_code == 400                                                      # already in the team
    assert client.post("/admin/api/team", json={"email": "a@x.in", "role": "king"}, headers=client.owner).status_code == 400
    me = client.get("/admin/api/me", headers=client.owner).json()
    owner_id = [m for m in client.get("/admin/api/team", headers=client.owner).json()["members"] if m["email"] == "owner@x.in"][0]["id"]
    assert client.put(f"/admin/api/team/{owner_id}", json={"role": "support"}, headers=client.owner).status_code == 400
    assert me["role_label"] == "Super Admin" and "team" in me["caps"]
    h = member(client, "support")
    sid = [m for m in client.get("/admin/api/team", headers=client.owner).json()["members"] if m["email"] == "support@x.in"][0]["id"]
    # switch off → the open session ends and login is refused
    assert client.put(f"/admin/api/team/{sid}", json={"active": False}, headers=client.owner).status_code == 200
    assert client.get("/admin/api/overview", headers=h).status_code == 401
    assert client.post("/admin/api/login", json={"email": "support@x.in", "password": "Mine2026x"}).status_code == 401
    # back on + password reset → new one-time password, old one stops working
    client.put(f"/admin/api/team/{sid}", json={"active": True}, headers=client.owner)
    tmp = client.post(f"/admin/api/team/{sid}/reset", headers=client.owner).json()["temp_password"]
    assert client.post("/admin/api/login", json={"email": "support@x.in", "password": "Mine2026x"}).status_code == 401
    assert client.post("/admin/api/login", json={"email": "support@x.in", "password": tmp}).json()["must_change"] is True
    # the one-time password is never written to the audit log
    log = client.get("/admin/api/audit", headers=client.owner).json()["items"]
    assert all(tmp not in (x["details"] or "") for x in log) and any(x["what"] == "Added a team member" for x in log)
