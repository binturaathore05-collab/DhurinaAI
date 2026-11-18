"""Step 3: the institute's own panel — login set by Super Admin, its own data only."""
import base64
import importlib

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
    for tid, name in (("subhash", "Subhash Sir"), ("other", "Other Academy")):
        main.db.execute("INSERT INTO teachers (id, name, subject) VALUES (?, ?, 'History')", (tid, name))
    admin = TestClient(main.app)
    admin.headers["Authorization"] = "Bearer " + admin.post(
        "/admin/api/login", json={"email": "owner@dhurina.in", "password": "Dhurina2026"}).json()["token"]
    return admin, main


def _panel(main, admin, tid, login):
    temp = admin.put(f"/admin/api/teachers/{tid}/panel-login", json={"login": login}).json()["password"]
    c = TestClient(main.app)
    r = c.post("/teacher/login", json={"login": login, "password": temp}).json()
    assert r["must_change"]
    c.headers["Authorization"] = "Bearer " + r["token"]
    return c, temp


def test_login_home_and_password_change(setup):
    admin, main = setup
    c, temp = _panel(main, admin, "subhash", "subhash@example.com")
    h = c.get("/teacher/home").json()
    assert h["me"]["name"] == "Subhash Sir" and h["me"]["must_change"] and h["faculty"] == 1 and len(h["months"]) == 6
    assert c.post("/teacher/password", json={"current_password": "wrong", "new_password": "NewPass2026"}).status_code == 400
    assert c.post("/teacher/password", json={"current_password": temp, "new_password": "short"}).status_code == 400
    r = c.post("/teacher/password", json={"current_password": temp, "new_password": "NewPass2026"}).json()
    assert c.get("/teacher/home").status_code == 401                     # the old login ended …
    assert c.get("/teacher/home", headers={"Authorization": "Bearer " + r["token"]}).status_code == 200   # … this one goes on
    r = TestClient(main.app).post("/teacher/login", json={"login": "SUBHASH@example.com", "password": "NewPass2026"}).json()
    assert not r["must_change"] and r["institute"] == "subhash"
    assert any(a["who"] == "teacher:subhash" and a["path"] == "/teacher/password"
               for a in main.db.all("SELECT who, path FROM admin_audit"))


def test_wrong_passwords_lock_and_logins_are_unique(setup):
    admin, main = setup
    admin.put("/admin/api/teachers/subhash/panel-login", json={"login": "98765 43210"})
    assert admin.put("/admin/api/teachers/other/panel-login", json={"login": "9876543210"}).status_code == 400
    c = TestClient(main.app)
    for _ in range(5):
        assert c.post("/teacher/login", json={"login": "9876543210", "password": "nope1234"}).status_code == 400
    assert "Too many" in c.post("/teacher/login", json={"login": "9876543210", "password": "nope1234"}).json()["detail"]
    assert c.post("/teacher/login", json={"login": "nobody@x.in", "password": "x"}).json()["detail"] == "Wrong login or password"


def test_an_institute_sees_and_changes_only_its_own_things(setup):
    admin, main = setup
    a, _ = _panel(main, admin, "subhash", "subhash@example.com")
    b, _ = _panel(main, admin, "other", "other@example.com")
    f = a.post("/teacher/faculty", json={"name": "Gupta Sir", "subjects": ["maths"]}).json()
    assert b.put(f"/teacher/faculty/{f['id']}", json={"name": "x"}).status_code == 404
    up = a.post("/teacher/library", json={"filename": "Maths/pct.txt",
                "data_base64": base64.b64encode(b"Profit percentage equals profit by cost price times 100.").decode()}).json()
    assert up["subject"] == "maths" and a.get(f"/teacher/library/{up['id']}").json()["text"].startswith("Profit")
    assert b.get(f"/teacher/library/{up['id']}").status_code == 404
    assert b.get("/teacher/library").json()["total"] == 0
    assert a.get("/teacher/home").json()["files"]["total"] == 1
    assert a.delete(f"/teacher/faculty/{f['id']}").json()["ok"]
    # the old teacher key still works for scripts; a wrong one never
    assert TestClient(main.app).get("/teacher/home", headers={"X-Teacher-Id": "subhash", "X-Teacher-Key": "x"}).status_code == 403


def test_flagged_students_hide_the_number_from_the_institute(setup):
    admin, main = setup
    a, _ = _panel(main, admin, "subhash", "subhash@example.com")
    from app.services import student_safety
    sid = main.db.execute("INSERT INTO students (teacher_id, phone, name) VALUES ('subhash', '+919876500001', 'Ravi')").lastrowid
    student_safety.record_violation(main.db, sid, "subhash", "minor", "harassment", "tu pagal hai", None,
                                    student_safety.safety_settings(main.admin.get_settings(main.db)))
    item = a.get("/teacher/safety?status=all").json()["items"][0]
    assert "9876500001" not in item["phone"] and item["phone"].endswith("0001")
    d = a.get(f"/teacher/safety/{sid}").json()
    assert d["violations"][0]["question"] == "tu pagal hai" and "98765" not in d["phone"]
