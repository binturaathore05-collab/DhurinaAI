"""Super Admin pauses / blocks a whole institute; students, payments, sign-ups and the panel follow."""
import importlib
import re
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "i.db"))
    monkeypatch.setenv("ADMIN_EMAIL", "owner@dhurina.in")
    monkeypatch.setenv("ADMIN_PASSWORD", "Dhurina2026")
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name) VALUES ('demo', 'Demo Sir')")
    main.db.execute("INSERT INTO plans (id, teacher_id, name, amount_paise, duration_days, active) VALUES ('demo-monthly', 'demo', 'Month', 49900, 30, 1)")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    c = TestClient(main.app)
    tok = c.post("/admin/api/login", json={"email": "owner@dhurina.in", "password": "Dhurina2026"}).json()["token"]
    adm = {"Authorization": "Bearer " + tok}
    app_h = {"X-Teacher-Id": "demo"}

    def student(phone):
        c.post("/auth/otp", json={"phone": phone}, headers=app_h)
        r = c.post("/auth/verify", json={"phone": phone, "code": re.search(r"\d{6}", sent[-1]).group()}, headers=app_h)
        return r
    return c, main, adm, app_h, student


def test_pause_stops_ai_and_new_plans_then_ends_by_itself(setup):
    c, main, adm, app_h, student = setup
    h = {**app_h, "Authorization": "Bearer " + student("9876500001").json()["token"]}
    assert c.post("/admin/api/teachers/demo/account", json={"state": "paused", "reason": ""}, headers=adm).status_code == 400
    r = c.post("/admin/api/teachers/demo/account", json={"state": "paused", "reason": "Fees due", "until_days": 3}, headers=adm)
    assert r.json()["account"]["state"] == "paused"
    a = c.get("/me/access", headers=h).json()
    assert "paused" in a["service_message"]
    ask = c.post("/class/ask", json={"question": "What is photosynthesis?"}, headers=h)
    assert ask.status_code == 403 and "paused" in ask.json()["detail"]
    plan = main.db.one("SELECT id FROM plans")["id"]
    assert c.post("/pay/checkout", json={"plan_id": str(plan)}, headers=h).status_code == 403
    assert student("9876500002").status_code == 200   # a pause still lets new students in (for notes/library)
    assert main.db.one("SELECT 1 FROM alerts WHERE kind = 'institute'")
    # the date passes → active again by itself
    main.db.execute("UPDATE teachers SET account_until = ? WHERE id = 'demo'", (time.time() - 1,))
    assert c.get("/me/access", headers=h).json()["service_message"] is None
    assert main.institute_status.history(main.db, "demo")[0]["by_who"] == "system"


def test_block_closes_signups_and_the_panel(setup):
    c, main, adm, app_h, student = setup
    old = student("9876500001")
    login = c.put("/admin/api/teachers/demo/panel-login", json={"login": "demo@inst.in"}, headers=adm).json()
    c.post("/admin/api/teachers/demo/account", json={"state": "blocked", "reason": "Complaints"}, headers=adm)
    assert c.post("/admin/api/teachers/demo/account", json={"state": "blocked", "reason": "x", "until_days": 2},
                  headers=adm).status_code == 400   # end dates are for a pause only
    new = c.post("/auth/otp", json={"phone": "9876500003"}, headers=app_h)
    assert new.status_code == 403 and "stopped" in new.json()["detail"]
    main.db.execute("DELETE FROM rate_events")   # (the OTP 30-second gap)
    assert student("9876500001").status_code == 200   # own students can still log in for notes
    pw = login.get("password") or login.get("temp_password")
    r = c.post("/teacher/login", json={"login": "demo@inst.in", "password": pw})
    assert r.status_code == 403 and "blocked" in r.json()["detail"]
    assert c.post("/admin/api/teachers/demo/build", headers=adm).status_code == 400
    # back to active: everything works again
    c.post("/admin/api/teachers/demo/account", json={"state": "active", "reason": "Sorted out"}, headers=adm)
    assert c.post("/auth/otp", json={"phone": "9876500003"}, headers=app_h).status_code == 200
    d = c.get("/admin/api/teachers/demo", headers=adm).json()
    assert d["account"]["state"] == "active" and [x["new_status"] for x in d["account_history"]] == ["active", "blocked"]
    assert old.status_code == 200


def test_only_super_admin_can_change_it(setup):
    c, main, adm, app_h, student = setup
    pw = c.post("/admin/api/team", json={"email": "t@dhurina.in", "name": "T", "role": "technical"}, headers=adm).json()["temp_password"]
    t = c.post("/admin/api/login", json={"email": "t@dhurina.in", "password": pw}).json()["token"]
    c.post("/admin/api/password", json={"current_password": pw, "new_password": "Tech2026xx"}, headers={"Authorization": "Bearer " + t})
    t = c.post("/admin/api/login", json={"email": "t@dhurina.in", "password": "Tech2026xx"}).json()["token"]
    r = c.post("/admin/api/teachers/demo/account", json={"state": "paused", "reason": "x"}, headers={"Authorization": "Bearer " + t})
    assert r.status_code == 403
    assert c.get("/admin/api/teachers/demo", headers={"Authorization": "Bearer " + t}).json()["can_account"] is False
