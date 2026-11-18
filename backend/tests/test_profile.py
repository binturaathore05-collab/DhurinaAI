"""App → My Library → Profile: name, number, plan, change number, logout (owner, 18 Nov 2026)."""
import importlib
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name) VALUES ('demo', 'Demo Sir')")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append((phone, msg))
    c = TestClient(main.app)
    c.headers["X-Teacher-Id"] = "demo"

    def login(phone):
        c.post("/auth/otp", json={"phone": phone})
        return c.post("/auth/verify", json={"phone": phone, "code": re.search(r"\d{6}", sent[-1][1]).group()}).json()["token"]
    return c, main, sent, login


def test_profile_shows_the_account(setup):
    c, main, sent, login = setup
    h = {"Authorization": "Bearer " + login("9876500001")}
    c.put("/me/name", json={"name": "Ravi"}, headers=h)
    p = c.get("/me", headers=h).json()
    assert p["name"] == "Ravi" and p["phone"] == "+919876500001" and p["state"] == "demo" and p["plan"]["active"] is False


def test_change_number_needs_the_code_from_the_new_number(setup):
    c, main, sent, login = setup
    h = {"Authorization": "Bearer " + login("9876500001")}
    login("9876500002")   # someone else's account
    assert c.post("/me/phone/otp", json={"phone": "9876500001"}, headers=h).status_code == 400   # own number
    assert "already has an account" in c.post("/me/phone/otp", json={"phone": "9876500002"}, headers=h).json()["detail"]
    assert c.post("/me/phone/otp", json={"phone": "9876500003"}, headers=h).json()["sent"]
    assert sent[-1][0] == "+919876500003"
    assert c.post("/me/phone/verify", json={"phone": "9876500003", "code": "000000"}, headers=h).status_code == 400
    code = re.search(r"\d{6}", sent[-1][1]).group()
    r = c.post("/me/phone/verify", json={"phone": "9876500003", "code": code}, headers=h).json()
    assert r["phone"] == "+919876500003"
    assert c.get("/me", headers=h).status_code == 401   # S3: a new number ends the old logins…
    h = {"Authorization": "Bearer " + r["token"]}       # …and this phone gets a fresh one
    assert c.get("/me", headers=h).json()["phone"] == "+919876500003"   # same account
    assert main.db.one("SELECT COUNT(*) AS n FROM students")["n"] == 2   # moved, not a new account
    assert not main.db.one("SELECT 1 FROM students WHERE phone = '+919876500001'")


def test_saying_profile_opens_it(setup):
    c, main, sent, login = setup
    h = {"Authorization": "Bearer " + login("9876500001")}
    assert c.post("/class/ask", json={"question": "Sir mera profile kholo"}, headers=h).json()["type"] == "profile"
    assert c.post("/class/ask", json={"question": "Sir, mera number badlo"}, headers=h).json()["type"] == "profile"
