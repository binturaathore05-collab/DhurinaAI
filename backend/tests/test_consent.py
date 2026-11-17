"""B1 · Class at signup + parent consent by OTP for under-18s, enforced on the server."""
import importlib
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

pytestmark = pytest.mark.consent_gate   # the real gate, not switched off


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "c.db"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Teacher', 'History')")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append((phone, msg))
    from app.services import admin
    admin.save_settings(main.db, {"limits": {"otp_gap_seconds": 1, "otp_per_phone_10min": 100, "otp_per_ip_hour": 100,
                                             "otp_per_device_day": 100}})
    c = TestClient(main.app)
    c.headers["X-Teacher-Id"] = "demo"
    c.sent, c.main = sent, main
    c.post("/auth/otp", json={"phone": "9876543210"})
    code = re.search(r"\d{6}", sent[-1][1]).group()
    r = c.post("/auth/verify", json={"phone": "9876543210", "code": code})
    c.headers["Authorization"] = "Bearer " + r.json()["token"]
    c.login = r.json()
    c.sid = main.db.one("SELECT id FROM students")["id"]
    return c


def ask(c):
    return c.post("/class/ask", json={"question": "Who was Akbar?"})


def test_new_student_must_give_class_first(client):
    assert client.login["profile_needed"] and not client.login["consent_needed"]
    opts = [o["value"] for o in client.login["class_options"]]
    assert opts[0] == "6" and opts[-1] == "college" and "5" not in opts          # class 6 and above (owner)
    r = ask(client)
    assert r.status_code == 428 and "class" in r.json()["detail"]
    assert client.get("/library").status_code == 200                          # non-AI parts still work
    assert client.put("/me/profile", json={"class_level": "4", "is_adult": False}).status_code == 400


def test_adult_starts_straight_away(client):
    a = client.put("/me/profile", json={"class_level": "college", "is_adult": True}).json()
    assert a["consent"] == "not_needed" and not a["consent_needed"]
    assert ask(client).status_code == 200


def test_under_18_needs_parent_code(client):
    a = client.put("/me/profile", json={"class_level": "8", "is_adult": False}).json()
    assert a["consent_needed"]
    r = ask(client)
    assert r.status_code == 428 and "parent" in r.json()["detail"]
    assert client.post("/tests", json={"mode": "mcq"}).status_code == 428
    # own number is refused
    assert client.post("/me/parent/otp", json={"phone": "9876543210"}).status_code == 400
    assert client.post("/me/parent/otp", json={"phone": "9812345678"}).status_code == 200
    phone, sms = client.sent[-1]
    assert phone == "+919812345678" and "allow your child" in sms and "Demo Teacher" in sms
    code = re.search(r"\d{6}", sms).group()
    assert client.post("/me/parent/verify", json={"phone": "9812345678", "code": "000000"}).status_code == 400
    a = client.post("/me/parent/verify", json={"phone": "9812345678", "code": code}).json()
    assert a["consent"] == "given" and not a["consent_needed"] and a["parent_phone"] == "+91•••••678"
    assert ask(client).status_code == 200
    row = client.main.db.one("SELECT * FROM parent_consents")
    assert row["parent_phone"] == "+919812345678" and row["notice_version"] and row["ip"] and row["given_at"]
    assert client.post("/me/parent/otp", json={"phone": "9812345678"}).status_code == 400   # already given


def test_parent_code_cannot_be_a_login_code(client):
    """A login code for the parent's number must not work as the parent's OK (separate codes)."""
    client.put("/me/profile", json={"class_level": "8", "is_adult": False})
    client.post("/auth/otp", json={"phone": "9812345678"})                    # login code to that number
    login_code = re.search(r"\d{6}", client.sent[-1][1]).group()
    r = client.post("/me/parent/verify", json={"phone": "9812345678", "code": login_code})
    assert r.status_code == 400 and client.get("/me/access").json()["consent_needed"]


def test_admin_sees_and_can_withdraw_consent(client):
    from app.services import admin_auth
    client.put("/me/profile", json={"class_level": "10", "is_adult": False})
    client.post("/me/parent/otp", json={"phone": "9812345678"})
    code = re.search(r"\d{6}", client.sent[-1][1]).group()
    client.post("/me/parent/verify", json={"phone": "9812345678", "code": code})
    admin_auth.create_admin(client.main.db, "owner@x.in", "Passw0rd1", "Owner", "owner")
    h = {"Authorization": "Bearer " + client.post("/admin/api/login", json={"email": "owner@x.in", "password": "Passw0rd1"}).json()["token"]}
    d = client.get(f"/admin/api/students/{client.sid}", headers=h).json()
    assert d["class_level"] == "10" and d["consent_status"] == "given" and d["consents"][0]["parent_phone"] == "+91•••••678"
    assert client.post(f"/admin/api/students/{client.sid}/consent/revoke", headers=h, json={"reason": ""}).status_code == 400
    d = client.post(f"/admin/api/students/{client.sid}/consent/revoke", headers=h,
                    json={"reason": "Father called to withdraw"}).json()
    assert d["consent_status"] == "withdrawn" and d["consents"][0]["revoked_by"] == "owner@x.in"
    assert ask(client).status_code == 428                                     # AI stops until a parent allows again


def test_min_class_setting_and_class_in_prompt(client):
    from app.services import admin
    admin.save_settings(client.main.db, {"students": {"min_class": 9}})
    assert client.put("/me/profile", json={"class_level": "8", "is_adult": False}).status_code == 400
    with pytest.raises(admin.AdminError):
        admin.save_settings(client.main.db, {"students": {"min_class": 13}})
    client.put("/me/profile", json={"class_level": "college", "is_adult": True})
    ask(client)
    system = [c for c in client.main.raw_llm.calls if "Return JSON only" in c[0]][-1][0]
    assert "college or preparing for a competitive exam" in system
