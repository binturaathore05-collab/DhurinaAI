"""B6 · Encryption at rest, retention, delete-my-data (app, call phrase, admin), daily encrypted backups."""
import importlib
import os
import re
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "test-key-123")
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Teacher', 'History')")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    from app.services import admin_auth
    admin_auth.create_admin(main.db, "owner@x.in", "Passw0rd1", "Owner", "owner")
    c = TestClient(main.app)
    c.main, c.tmp, c.sent = main, tmp_path, sent
    c.admin = {"Authorization": "Bearer " + c.post("/admin/api/login", json={"email": "owner@x.in", "password": "Passw0rd1"}).json()["token"]}
    c.s = student(c, "9876543210")
    return c


def student(c, phone):
    c.post("/auth/otp", json={"phone": phone}, headers={"X-Teacher-Id": "demo"})
    code = re.search(r"\d{6}", c.sent[-1]).group()
    tok = c.post("/auth/verify", json={"phone": phone, "code": code}, headers={"X-Teacher-Id": "demo"}).json()["token"]
    return {"X-Teacher-Id": "demo", "Authorization": "Bearer " + tok}


def test_database_and_backups_are_encrypted(client):
    client.post("/class/ask", json={"question": "Haldighati yudh ka saal batao"}, headers=client.s)
    raw = open(client.tmp / "p.db", "rb").read()
    assert b"Haldighati" not in raw and b"9876543210" not in raw and not raw.startswith(b"SQLite format 3")
    d = client.post("/admin/api/data/backup", headers=client.admin).json()
    assert d["encrypted"] and len(d["backups"]) == 1 and d["last_backup"]["encrypted"]
    bk = open(client.tmp / "backups" / d["backups"][0]["file"], "rb").read()
    assert b"Haldighati" not in bk
    from app.db import Database
    copy = Database(str(client.tmp / "backups" / d["backups"][0]["file"]), "test-key-123")
    assert copy.one("SELECT question FROM qa_history")["question"] == "Haldighati yudh ka saal batao"


def test_retention_deletes_old_conversations_keeps_what_must_stay(client):
    for q in ["old one", "old kept by a case", "new one"]:
        client.post("/class/ask", json={"question": q}, headers=client.s)
    db = client.main.db
    db.execute("UPDATE qa_history SET created_at = '2024-01-01 00:00:00' WHERE question LIKE 'old%'")
    kept = db.one("SELECT id FROM qa_history WHERE question = 'old kept by a case'")["id"]
    db.execute("INSERT INTO incidents (created_at, last_at, kind, severity, status, student_id, qa_id, title) "
               "VALUES (1, 1, 'report', 'high', 'open', 1, ?, 't')", (kept,))
    db.execute("INSERT INTO student_violations (student_id, teacher_id, severity, category, question, at) "
               "VALUES (1, 'demo', 'minor', 'x', 'q', ?)", (time.time() - 40 * 31 * 86400,))
    d = client.post("/admin/api/data/cleanup", headers=client.admin).json()
    assert d["last_cleanup"]["answers"] == 1 and d["last_cleanup"]["flagged_messages"] == 1
    assert [r["question"] for r in db.all("SELECT question FROM qa_history ORDER BY id")] == ["old kept by a case", "new one"]
    # the newest answer's seal still checks out although the answer before it was deleted
    new = db.one("SELECT verify_code FROM qa_history WHERE question = 'new one'")["verify_code"]
    it = client.get("/admin/api/verify", params={"q": new}, headers=client.admin).json()["items"][0]
    assert it["untouched"] and it["chain_ok"]


def test_delete_my_data_from_the_app_and_the_call(client):
    r = client.post("/class/ask", json={"question": "Sir mera data delete kar do"}, headers=client.s).json()
    assert r["type"] == "delete_offer"                                     # nothing deleted yet, the app asks first
    assert client.main.db.one("SELECT COUNT(*) AS n FROM qa_history")["n"] == 0
    client.post("/class/ask", json={"question": "Who was Akbar?"}, headers=client.s)
    assert client.post("/me/delete", json={"confirm": "yes"}, headers=client.s).status_code == 400
    d = client.post("/me/delete", json={"confirm": "DELETE"}, headers=client.s).json()
    assert d["deleted"] and d["answers"] == 1
    row = client.main.db.one("SELECT phone, name, status FROM students WHERE id = 1")
    assert row["phone"] == "deleted:1" and row["name"] is None and row["status"] == "disabled"
    assert client.get("/library", headers=client.s).status_code == 403       # the old login no longer works
    log = client.get("/admin/api/data", headers=client.admin).json()["requests"]
    assert log[0]["requested_by"] == "student" and log[0]["details"]["answers"] == 1
    # the same number can sign up again as a brand-new account (after the usual 30-second code gap)
    client.main.db.execute("DELETE FROM rate_events")
    assert student(client, "9876543210")["Authorization"]
    assert client.main.db.one("SELECT COUNT(*) AS n FROM students WHERE phone = '+919876543210'")["n"] == 1


def test_admin_deletes_on_parent_request_with_roles(client):
    from app.services import admin_auth
    uid, tmp = admin_auth.add_member(client.main.db, "sup@x.in", "Sup", "support", "owner@x.in", {"support": 1})
    admin_auth.change_password(client.main.db, uid, tmp, "Support2026x")
    sup = {"Authorization": "Bearer " + client.post("/admin/api/login", json={"email": "sup@x.in", "password": "Support2026x"}).json()["token"]}
    assert client.get("/admin/api/data", headers=sup).status_code == 403          # backups: Super Admin only
    assert client.post("/admin/api/students/1/delete", headers=sup, json={"reason": ""}).status_code == 400
    assert client.post("/admin/api/students/1/delete", headers=sup, json={"reason": "Mother called"}).status_code == 200
    assert client.post("/admin/api/students/1/delete", headers=sup, json={"reason": "again"}).status_code == 400


def test_daily_jobs_and_settings(client):
    from app.services import admin, data_protection
    done = data_protection.daily(client.main.db, lambda: admin.get_settings(client.main.db), str(client.tmp / "b2"))
    assert done == ["backup", "retention", "restore_test"]               # B9: weekly restore test of the newest backup
    assert data_protection.last_job(client.main.db, "restore_test")["ok"] is True
    assert data_protection.daily(client.main.db, lambda: admin.get_settings(client.main.db), str(client.tmp / "b2")) == []
    with pytest.raises(admin.AdminError):
        admin.save_settings(client.main.db, {"data": {"conversation_months": 24, "safety_months": 12}})
    for i in range(5):
        data_protection.backup_now(client.main.db, str(client.tmp / "b3"), keep=3, now=time.time() + i)
    assert len(os.listdir(client.tmp / "b3")) == 3                          # only the newest are kept


def test_plain_database_becomes_encrypted_when_a_key_is_set(tmp_path):
    from app.db import Database, EncryptionError
    p = str(tmp_path / "old.db")
    Database(p).execute("INSERT INTO teachers (id, name, subject) VALUES ('t', 'Plain Sir', 'x')")
    assert b"Plain Sir" in open(p, "rb").read()
    assert Database(p, "k").one("SELECT name FROM teachers")["name"] == "Plain Sir"
    assert b"Plain Sir" not in open(p, "rb").read()
    with pytest.raises(EncryptionError):
        Database(p, "wrong")
