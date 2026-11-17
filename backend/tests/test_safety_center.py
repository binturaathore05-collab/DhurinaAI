"""B9 · Safety Center: content filters, messages the admin can change, parent SMS, backup restore test."""
import importlib
import os
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


class Clf:
    def __init__(self):
        self.prompts = []

    def chat_json(self, system, user):
        self.prompts.append(system)
        if "RUDEQ" in user:
            return {"category": "harassment", "severity": "minor"}
        if "HACKQ" in user:
            return {"category": "crime", "severity": "serious"}
        if "SADQ" in user:
            return {"category": "self_harm", "severity": "serious"}
        if "WEAPONQ" in user:
            return {"category": "weapons", "severity": "serious"}
        return {"category": "none", "severity": "none"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "c.db"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Sir', 'History')")
    sent, parent_sms = [], []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    clf = Clf()
    main.moderator.provider, main.moderator.llm = "llm", clf
    from app.services import admin_auth, parent_notify
    monkeypatch.setitem(parent_notify.sender, "sms", lambda phone, msg: parent_sms.append((phone, msg)))
    admin_auth.create_admin(main.db, "owner@x.in", "Passw0rd1", "Owner", "owner")
    c = TestClient(main.app)
    c.main, c.clf, c.parent_sms = main, clf, parent_sms
    c.admin = {"Authorization": "Bearer " + c.post("/admin/api/login", json={"email": "owner@x.in", "password": "Passw0rd1"}).json()["token"]}
    c.post("/auth/otp", json={"phone": "9876543210"}, headers={"X-Teacher-Id": "demo"})
    code = re.search(r"\d{6}", sent[-1]).group()
    t = c.post("/auth/verify", json={"phone": "9876543210", "code": code}, headers={"X-Teacher-Id": "demo"}).json()["token"]
    c.s = {"X-Teacher-Id": "demo", "Authorization": "Bearer " + t}
    main.db.execute("UPDATE students SET name = 'Ravi', class_level = '7', is_adult = 0, consent_status = 'given', "
                    "parent_phone = '9811122233' WHERE id = 1")
    main.db.execute("INSERT INTO subscriptions (student_id, plan_id, starts_at, ends_at) VALUES (1, 'p', 0, 9999999999)")
    put(c, {"safety": {"auto_block": False}})   # these tests look at filters, not at the warnings ladder
    return c


def ask(c, q):
    r = c.post("/class/ask", json={"question": q}, headers=c.s)
    assert r.status_code == 200, r.text
    return r.json()


def put(c, data):
    return c.put("/admin/api/settings", json=data, headers=c.admin)


# ---------- content filters ----------

def test_defaults_keep_todays_behaviour(client):
    from app.services import content_filters
    f = content_filters.settings_of({})
    assert all(f[c]["on"] for c in f)
    assert ask(client, "RUDEQ you are stupid")["scope"] == "blocked"     # small problem → study redirect
    assert ask(client, "HACKQ how to hack my school's site")["scope"] == "unsafe"   # serious → refusal


def test_child_protection_filters_can_never_be_lowered(client):
    for bad in ({"sexual": {"on": False}}, {"weapons": {"severity": "minor"}}, {"self_harm": {"review": False}},
                {"drugs": {"on": "false"}}, {"jailbreak": {"on": False}}):
        r = put(client, {"filters": bad})
        assert r.status_code == 400 and "always on" in r.json()["detail"]
    assert put(client, {"filters": {"violence": {"level": "loud"}}}).status_code == 400


def test_filter_off_lets_student_messages_through_but_ai_answers_are_still_checked(client):
    r = put(client, {"filters": {"harassment": {"on": False, "level": "age", "severity": "auto", "review": False}}})
    assert r.status_code == 200, r.text
    assert ask(client, "RUDEQ you are stupid")["scope"] != "blocked"
    from app.services import content_filters
    from app.services.moderation import Verdict
    s = client.main.admin.get_settings(client.main.db)
    out = content_filters.apply(Verdict("harassment", "minor", "model"), "output", s)
    assert not out.safe                                                  # Sir's own answer: still checked


def test_filter_severity_and_human_review(client):
    put(client, {"filters": {"harassment": {"on": True, "level": "age", "severity": "serious", "review": True}}})
    assert ask(client, "RUDEQ you are stupid")["scope"] == "unsafe"     # now counts as serious
    case = client.main.db.one("SELECT kind FROM incidents ORDER BY id DESC LIMIT 1")
    assert case["kind"] == "serious_request"
    put(client, {"filters": {"personal_info": {"on": True, "level": "age", "severity": "minor", "review": True}}})
    client.clf.chat_json = lambda system, user: {"category": "personal_info", "severity": "minor"}
    ask(client, "what is your teacher's phone number")
    assert client.main.db.one("SELECT kind FROM incidents ORDER BY id DESC LIMIT 1")["kind"] == "filter_review"


def test_filter_level_reaches_the_safety_checker(client):
    put(client, {"filters": {"violence": {"on": True, "level": "strict", "severity": "auto", "review": False}}})
    ask(client, "tell me about the battle of haldighati")
    assert "violence: be extra careful" in client.clf.prompts[-1]
    assert "a real syllabus question is still none" in client.clf.prompts[-1]


# ---------- messages ----------

def test_admin_can_change_student_messages(client):
    msg = {"safety_refusal": {"en": "Not in our class, friend. Ask from your book!", "hi": "यह हमारी क्लास में नहीं। किताब से पूछो!"}}
    assert put(client, {"messages": msg}).status_code == 200
    a = ask(client, "WEAPONQ how to make it")
    assert a["answer"] in (msg["safety_refusal"]["en"], msg["safety_refusal"]["hi"])
    # blank = back to the built-in text
    put(client, {"messages": {"safety_refusal": {"en": "", "hi": ""}}})
    from app.i18n import MESSAGES
    assert ask(client, "WEAPONQ how to make it again")["answer"] in MESSAGES["safety_refusal"].values()


def test_message_rules(client):
    assert put(client, {"messages": {"care_message": {"en": "Please talk to someone."}}}).status_code == 400   # helpline kept
    assert put(client, {"messages": {"safety_suspended": {"en": "Paused for a while."}}}).status_code == 400   # {wait} kept
    assert put(client, {"messages": {"safety_suspended": {"en": "Paused. Back in {wait}."}}}).status_code == 200
    assert put(client, {"messages": {"safety_refusal": {"en": "No {name}"}}}).status_code == 400
    assert put(client, {"messages": {"notes_title": {"en": "x"}}}).status_code == 200   # unknown keys are ignored
    assert "notes_title" not in client.main.admin.get_settings(client.main.db)["messages"]


def test_policy_versions_include_b9_sections_only_when_changed(client):
    from app.services import policy
    s = client.main.admin.get_settings(client.main.db)
    assert "filters" not in policy.snapshot(s)
    put(client, {"filters": {"violence": {"on": True, "level": "strict", "severity": "auto", "review": False}}, "_note": "stricter"})
    v = client.get("/admin/api/policy", headers=client.admin).json()
    assert v["items"][0]["note"] == "stricter"
    cmp = client.get(f"/admin/api/policy/compare?a=1&b={v['current']}", headers=client.admin).json()
    assert any(ch["label"].startswith("Filter “Violence") for ch in cmp["changes"])
    r = client.post("/admin/api/policy/1/rollback", json={"note": "undo"}, headers=client.admin)
    assert r.status_code == 200, r.text
    assert client.main.admin.get_settings(client.main.db)["filters"]["violence"]["level"] == "age"


# ---------- parent SMS ----------

def test_parent_sms_when_blocked_never_with_the_childs_words(client):
    r = client.post("/admin/api/students/1/status", json={"action": "suspend", "reason": "test", "hours": 2}, headers=client.admin)
    assert r.status_code == 200, r.text
    assert len(client.parent_sms) == 1
    phone, text = client.parent_sms[0]
    assert phone == "9811122233" and "Ravi" in text and "WEAPONQ" not in text
    # once a day only
    client.post("/admin/api/students/1/status", json={"action": "unblock", "reason": "ok"}, headers=client.admin)
    client.post("/admin/api/students/1/status", json={"action": "suspend", "reason": "again", "hours": 2}, headers=client.admin)
    assert len(client.parent_sms) == 1
    hist = client.get("/admin/api/students/1", headers=client.admin).json()["parent_notices"]
    assert [h["status"] for h in hist][:2] == ["repeat", "sent"] and hist[0]["phone"].endswith("2233")


def test_no_parent_sms_for_adults_or_when_off(client):
    put(client, {"parents": {"notify_block": False}})
    client.post("/admin/api/students/1/status", json={"action": "suspend", "reason": "x", "hours": 1}, headers=client.admin)
    assert client.parent_sms == []
    put(client, {"parents": {"notify_block": True}})
    client.main.db.execute("UPDATE students SET is_adult = 1 WHERE id = 1")
    client.post("/admin/api/students/1/status", json={"action": "disable", "reason": "y"}, headers=client.admin)
    assert client.parent_sms == []


def test_care_sms_is_a_persons_decision_by_default(client):
    ask(client, "SADQ I feel so alone")
    assert client.parent_sms == []                                       # default: a person decides
    case = client.main.db.one("SELECT id FROM incidents WHERE kind = 'care'")["id"]
    r = client.post(f"/admin/api/incidents/{case}/act", json={"action": "notify_parent", "note": "spoke to school"}, headers=client.admin)
    assert r.status_code == 200, r.text
    assert len(client.parent_sms) == 1 and "14416" in client.parent_sms[0][1] and "SADQ" not in client.parent_sms[0][1]
    assert any("SMS sent" in n["action"] for n in r.json()["timeline"])


def test_care_sms_automatic_when_chosen(client):
    put(client, {"parents": {"notify_care": "auto"}})
    ask(client, "SADQ nobody cares")
    assert len(client.parent_sms) == 1
    assert put(client, {"parents": {"notify_care": "sometimes"}}).status_code == 400


# ---------- backup restore ----------

def test_restore_test_and_apply(client, tmp_path):
    from app.services import data_protection
    r = client.post("/admin/api/data/restore-test", json={}, headers=client.admin)
    assert r.status_code == 400                                          # no backup yet
    client.post("/admin/api/data/backup", headers=client.admin)
    r = client.post("/admin/api/data/restore-test", json={}, headers=client.admin).json()
    assert r["result"]["ok"] is True and r["result"]["rows"]["students"] == 1
    assert r["result"]["audit_chain"]["ok"] is True
    assert r["last_restore_test"]["ok"] is True
    assert client.post("/admin/api/data/restore-test", json={"file": "../c.db"}, headers=client.admin).status_code == 400
    # a damaged backup fails and raises an alert
    name = r["backups"][0]["file"]
    bad = str(tmp_path / "backups" / "liveteach-20000101-000000.db")
    with open(bad, "wb") as f:
        f.write(b"not a database at all" * 100)
    r2 = client.post("/admin/api/data/restore-test", json={"file": os.path.basename(bad)}, headers=client.admin).json()
    assert r2["result"]["ok"] is False
    assert client.main.db.one("SELECT kind FROM alerts WHERE kind = 'backup_bad'")
    # apply (server stopped): the backup replaces a database, the old one is kept
    target = str(tmp_path / "restored.db")
    open(target, "wb").write(b"old")
    keep = data_protection.restore_apply(target, str(tmp_path / "backups" / name), client.main.db._key)
    assert open(keep, "rb").read() == b"old"
    from app.db import Database
    assert Database(target, client.main.db._key).one("SELECT name FROM students")["name"] == "Ravi"
    with pytest.raises(data_protection.DataError):
        data_protection.restore_apply(target, bad, client.main.db._key)


def test_safety_center_and_filters_pages(client):
    d = client.get("/admin/api/safety-center", headers=client.admin).json()
    assert d["filters"] == {"on": 10, "total": 10, "locked": 5, "custom_messages": 0}
    assert d["tests"]["state"] == "blocked" and d["privacy"]["parent_care_sms"] == "manual"
    f = client.get("/admin/api/filters", headers=client.admin).json()
    assert len(f["catalog"]) == 10 and f["messages"]["care_message"]["must"] == ["14416"]
    assert "14416" in f["messages"]["care_message"]["default"]["hi"]
