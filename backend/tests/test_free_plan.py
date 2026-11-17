"""Super Admin gives a tester a plan without payment (owner, 18 Nov 2026)."""
import importlib
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "f.db"))
    monkeypatch.setenv("ADMIN_EMAIL", "owner@dhurina.in")
    monkeypatch.setenv("ADMIN_PASSWORD", "Dhurina2026")
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name) VALUES ('demo', 'Demo Sir')")
    admin = TestClient(main.app)
    admin.headers["Authorization"] = "Bearer " + admin.post(
        "/admin/api/login", json={"email": "owner@dhurina.in", "password": "Dhurina2026"}).json()["token"]
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    st = TestClient(main.app)
    st.headers["X-Teacher-Id"] = "demo"
    st.post("/auth/otp", json={"phone": "9876500001"})
    r = st.post("/auth/verify", json={"phone": "9876500001", "code": re.search(r"\d{6}", sent[-1]).group()}).json()
    st.headers["Authorization"] = "Bearer " + r["token"]
    sid = main.db.one("SELECT id FROM students")["id"]
    return admin, st, main, sid


def test_free_plan_unlocks_the_class_and_never_counts_as_money(setup):
    admin, st, main, sid = setup
    for q in ("Q1", "Q2", "Q3"):
        st.post("/class/ask", json={"question": q})
    assert st.post("/class/ask", json={"question": "Q4"}).status_code == 402      # demo over
    assert admin.post(f"/admin/api/students/{sid}/free-plan", json={"days": 30, "reason": ""}).status_code == 400
    r = admin.post(f"/admin/api/students/{sid}/free-plan", json={"days": 30, "reason": "Testing"}).json()
    assert r["active"] and r["free_until"]
    assert st.get("/me/access").json()["state"] == "active"
    assert st.post("/class/ask", json={"question": "Q5"}).status_code == 200
    ov = admin.get("/admin/api/overview").json()
    assert ov["overview"]["active_plans"] == 0 and ov["overview"]["this_month"]["total_paise"] == 0
    assert admin.get(f"/admin/api/students/{sid}").json()["plan"]["free_until"]
    assert any(a["path"].endswith("/free-plan") for a in main.db.all("SELECT path FROM admin_audit"))
    admin.post(f"/admin/api/students/{sid}/free-plan/end")
    assert st.get("/me/access").json()["state"] != "active"


def test_only_super_admin_can_give_it():
    from app.services import roles
    assert roles.has("owner", "free_plan")
    assert not any(roles.has(r, "free_plan") for r in ("safety", "support", "technical", "auditor"))
