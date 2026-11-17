"""Admin panel API: add/edit teachers with their own split, settings, reports, builds."""
import base64
import importlib
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("AVATAR_DIR", str(tmp_path / "avatars"))
    monkeypatch.setenv("ADMIN_EMAIL", "owner@dhurina.in")
    monkeypatch.setenv("ADMIN_PASSWORD", "Dhurina2026")
    monkeypatch.setenv("SECRETS_KEY", "k" * 40)
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    c = TestClient(main.app)
    r = c.post("/admin/api/login", json={"email": "Owner@Dhurina.in", "password": "Dhurina2026"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = "Bearer " + r.json()["token"]
    return c, main


def test_admin_requires_login(setup):
    c, main = setup
    assert c.get("/admin/api/overview", headers={"Authorization": ""}).status_code == 401
    assert c.get("/admin").status_code == 200  # the page itself loads; data needs a login
    assert c.get("/admin/api/me").json()["role"] == "owner"
    raw = main.db.one("SELECT password_hash FROM admin_users")["password_hash"]
    assert raw.startswith("scrypt$") and "Dhurina2026" not in raw  # never stored in plain text


def test_wrong_password_and_lockout(setup):
    c, _ = setup
    anon = TestClient(c.app)
    for _ in range(5):
        r = anon.post("/admin/api/login", json={"email": "owner@dhurina.in", "password": "wrong-pass1"})
        assert r.status_code == 401 and r.json()["detail"] == "Wrong email or password"
    r = anon.post("/admin/api/login", json={"email": "owner@dhurina.in", "password": "Dhurina2026"})
    assert r.status_code == 401 and "Too many wrong passwords" in r.json()["detail"]
    assert anon.post("/admin/api/login", json={"email": "nobody@x.in", "password": "x"}).status_code == 401


def test_change_password_ends_old_sessions(setup):
    c, _ = setup
    assert c.post("/admin/api/password", json={"current_password": "nope", "new_password": "NewPass123"}).status_code == 400
    assert c.post("/admin/api/password", json={"current_password": "Dhurina2026", "new_password": "short"}).status_code == 400
    assert c.post("/admin/api/password", json={"current_password": "Dhurina2026", "new_password": "NewPass123"}).json()["changed"]
    assert c.get("/admin/api/overview").status_code == 401  # old login no longer works
    anon = TestClient(c.app)
    assert anon.post("/admin/api/login", json={"email": "owner@dhurina.in", "password": "NewPass123"}).status_code == 200


def test_add_teacher_with_own_split_and_secret(setup):
    c, main = setup
    photo = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8fakejpeg").decode()
    r = c.post("/admin/api/teachers", json={
        "id": "meena", "name": "Meena Ma'am", "subject": "Science", "brand_color": "#F472B6",
        "platform_percent": 25, "monthly_price": "499", "yearly_price": "3999", "demo_questions": "5",
        "razorpay_key_id": "rzp_live_x", "razorpay_key_secret": "super-secret-1234", "photo_base64": photo})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["teacher_percent"] == 75 and t["monthly_price"] == 499 and t["has_avatar"]
    assert t["razorpay_key_secret"] == "••••1234"  # never returned in full
    raw = main.db.one("SELECT razorpay_key_secret FROM teachers WHERE id = 'meena'")["razorpay_key_secret"]
    assert raw.startswith("enc:") and "super-secret" not in raw  # stored encrypted
    assert c.get("/teachers/meena/avatar").status_code == 200
    # duplicate id refused; bad split refused
    assert c.post("/admin/api/teachers", json={"id": "meena", "name": "X"}).status_code == 400
    assert c.post("/admin/api/teachers", json={"id": "x1", "name": "X", "platform_percent": 120}).status_code == 400
    # edit: change split, blank secret keeps the old one
    r = c.put("/admin/api/teachers/meena", json={"name": "Meena Ma'am", "platform_percent": 30, "razorpay_key_secret": ""})
    assert r.json()["teacher_percent"] == 70 and r.json()["razorpay_key_secret"] == "••••1234"
    ov = c.get("/admin/api/overview").json()
    assert ov["teachers"][0]["platform_percent"] == 30 and ov["overview"]["teachers"] == 1


def test_teacher_demo_limit_used_by_student_app(setup):
    c, main = setup
    c.post("/admin/api/teachers", json={"id": "meena", "name": "Meena", "demo_questions": 1})
    s = TestClient(main.app)
    s.headers["X-Teacher-Id"] = "meena"
    sent = []
    main.otp.sms_sender = lambda p, m: sent.append(m)
    s.post("/auth/otp", json={"phone": "9876543210"})
    import re
    tok = s.post("/auth/verify", json={"phone": "9876543210", "code": re.search(r"\d{6}", sent[-1]).group()}).json()
    assert tok["demo_questions_left"] == 1
    s.headers["Authorization"] = "Bearer " + tok["token"]
    assert s.post("/class/ask", json={"question": "Q1"}).status_code == 200
    assert s.post("/class/ask", json={"question": "Q2"}).status_code == 402


def test_settings_and_revenue_split_report(setup):
    c, main = setup
    s = c.put("/admin/api/settings", json={"defaults": {"platform_percent": 15}, "company": {"gstin": "08ABCDE1234F1Z5"}}).json()
    assert s["defaults"]["platform_percent"] == 15 and s["company"]["gstin"] == "08ABCDE1234F1Z5"
    assert c.put("/admin/api/settings", json={"defaults": {"platform_percent": 150}}).status_code == 400
    c.post("/admin/api/teachers", json={"id": "meena", "name": "Meena", "platform_percent": 25, "monthly_price": 1000})
    sid = main.accounts.get_or_create_student(main.db, "meena", "+919876543210")
    main.db.execute("INSERT INTO payments (student_id, plan_id, razorpay_order_id, amount_paise, platform_percent, status) "
                    "VALUES (?, 'meena-monthly', 'o1', 100000, 25, 'paid')", (sid,))
    d = c.get("/admin/api/teachers/meena").json()
    assert d["this_month"] == {"total_paise": 100000, "platform_paise": 25000, "teacher_paise": 75000}
    assert d["months"][-1]["total_paise"] == 100000
    r = c.post("/admin/api/teachers/meena/checklist", json={"item": "published", "done": True}).json()
    assert r["status"] == "live" and r["checklist"][-1]["done"]


def test_build_trigger_sends_teacher_config(setup, monkeypatch):
    c, main = setup
    c.post("/admin/api/teachers", json={"id": "meena", "name": "Meena", "app_name": "Meena Ma'am AI", "brand_color": "#F472B6"})
    calls = []
    monkeypatch.setattr(main.builds, "trigger_build",
                        lambda t, a, base: calls.append(("cfg", main.builds.app_config(t), a)))
    assert c.post("/admin/api/teachers/meena/build").json() == {"started": True}
    _, cfg, avatar = calls[-1]
    assert cfg["appName"] == "Meena Ma'am AI" and cfg["accent"] == "#F472B6" and cfg["teacherId"] == "meena"
    assert c.get("/admin/api/teachers/meena").json()["status"] == "building"


def test_build_without_github_token_explains(setup, monkeypatch):
    c, _ = setup
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    c.post("/admin/api/teachers", json={"id": "meena", "name": "Meena"})
    r = c.post("/admin/api/teachers/meena/build")
    assert r.status_code == 400 and "GITHUB_TOKEN" in r.json()["detail"]


def test_trigger_build_payload():
    from app.services import builds
    calls = []
    builds.trigger_build({"id": "meena", "name": "Meena", "app_name": None, "subject": "Sci", "brand_color": None},
                         "https://x/teachers/meena/avatar", "https://x", caller=lambda m, p, b=None: calls.append((m, p, b)))
    m, p, b = calls[0]
    assert p.endswith("/dispatches") and b["inputs"]["teacher_id"] == "meena"
    assert json.loads(b["inputs"]["teacher_config"])["appName"] == "Meena AI"


def test_teacher_with_several_subjects(setup):
    c, _ = setup
    t = c.post("/admin/api/teachers", json={"id": "anita", "name": "Anita", "subjects": ["History", "Geography", "History", " Polity "]}).json()
    assert t["subject"] == "History, Geography, Polity" and t["subjects"] == ["History", "Geography", "Polity"]


def test_admin_downloads_teacher_report(setup, monkeypatch):
    import time as _t
    c, main = setup
    c.post("/admin/api/teachers", json={"id": "meena", "name": "Meena", "platform_percent": 25, "monthly_price": 1000})
    month = _t.strftime("%Y-%m")
    j = c.get(f"/admin/api/teachers/meena/report?month={month}").json()
    assert j["summary"]["subscriptions"] == 0
    x = c.get(f"/admin/api/teachers/meena/report?month={month}&format=xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK" and "meena" in x.headers["content-disposition"]
    monkeypatch.setattr(main.notes_pdf, "render_pdf", lambda html, path: (open(path, "wb").write(b"%PDF-1.7"), path)[1])
    p = c.get(f"/admin/api/teachers/meena/report?month={month}&format=pdf")
    assert p.status_code == 200 and p.content.startswith(b"%PDF")
    assert c.get("/admin/api/teachers/meena/report?month=nov").status_code == 400


def test_admin_reports_api(setup):
    c, main = setup
    c.post("/admin/api/teachers", json={"id": "meena", "name": "Meena", "platform_percent": 25, "monthly_price": 500})
    sid = main.accounts.get_or_create_student(main.db, "meena", "+919876543210")
    main.db.execute("INSERT INTO payments (student_id, plan_id, razorpay_order_id, amount_paise, platform_percent, status) "
                    "VALUES (?, 'meena-monthly', 'o1', 50000, 25, 'paid')", (sid,))
    from app.services.teacher_data import TZ
    today = __import__("datetime").datetime.now(TZ).date().isoformat()   # "today" in India
    r = c.get(f"/admin/api/reports?date_from=2026-01-01&date_to={today}").json()
    assert r["summary"]["dhurina_paise"] == 12500 and r["by_teacher"][0]["name"] == "Meena"
    assert c.get(f"/admin/api/reports/payments?date_from=2026-01-01&date_to={today}").json()["total"] == 1
    x = c.get(f"/admin/api/reports/export?date_from=2026-01-01&date_to={today}&format=xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert c.get("/admin/api/reports?date_from=2026-12-01&date_to=2026-01-01").status_code == 400
    assert c.get("/admin/api/teachers/meena/students").json()["total"] == 1
    # teacher's % and money shown next to Dhurina's
    assert r["summary"]["teachers_paise"] == 37500 and r["summary"]["teachers_percent"] == 75
    pay = c.get(f"/admin/api/reports/payments?date_from=2026-01-01&date_to={today}").json()["items"][0]
    assert pay["teacher_percent"] == 75 and pay["teacher_paise"] == 37500
    # any period for one teacher's report: financial year / year / custom
    fy = c.get(f"/admin/api/teachers/meena/report?date_from=2026-04-01&date_to={today}").json()
    assert fy["summary"]["subscriptions"] == 1 and fy["period_from"] == "01 Apr 2026"
    assert fy["items"][0]["teacher_percent"] == 75 and fy["summary"]["teacher_percent"] == 75
    mine = c.get(f"/admin/api/teachers/meena/report?date_from=2026-04-01&date_to={today}&view=teacher").json()
    assert "dhurina" not in str(mine).lower() and mine["summary"]["your_paise"] == 37500
    assert c.get("/admin/api/teachers/meena/report?date_from=2027-03-31&date_to=2026-04-01").status_code == 400
    x = c.get(f"/admin/api/teachers/meena/report?date_from=2026-04-01&date_to={today}&format=xlsx")
    assert x.status_code == 200 and "2026-04-01-to-" in x.headers["content-disposition"]


def test_teacher_panel_page_is_served(setup):
    c = setup[0] if isinstance(setup, tuple) else setup
    r = c.get("/teacher-panel")
    assert r.status_code == 200 and "<html" in r.text.lower()
