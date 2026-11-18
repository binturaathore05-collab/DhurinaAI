"""S3 security: admin 2-step login, sessions, new-place alert, block list, logout everywhere, headers, limits."""
import importlib
import re
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.services import security  # noqa: E402

UA1, UA2 = "Mozilla/5.0 (Windows) Chrome", "Mozilla/5.0 (Android) Chrome"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "s.db"))
    monkeypatch.setenv("ADMIN_EMAIL", "owner@dhurina.in")
    monkeypatch.setenv("ADMIN_PASSWORD", "Dhurina2026")
    monkeypatch.setenv("SECRETS_KEY", "k" * 40)
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("TRUST_PROXY", "1")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    security._forget_cache()
    c = TestClient(main.app)

    def login(ip="203.0.113.1", ua=UA1, email="owner@dhurina.in", pw="Dhurina2026"):
        return c.post("/admin/api/login", json={"email": email, "password": pw},
                      headers={"X-Forwarded-For": ip, "User-Agent": ua})
    return c, main, login


def H(tok, ip="203.0.113.1"):
    return {"Authorization": "Bearer " + tok, "X-Forwarded-For": ip}


def test_totp_matches_the_standard():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"   # RFC 6238 test key "12345678901234567890"
    assert security.code_at(secret, 59) == "287082"
    assert security.match_step(secret, "287082", None, 59) == 1
    assert security.match_step(secret, "287082", 1, 59) is None   # the same code can't be used twice
    assert security.match_step(secret, "000000", None, 59) is None


def test_two_step_login(setup):
    c, main, login = setup
    tok = login().json()["token"]
    start = c.post("/admin/api/2step/start", headers=H(tok)).json()
    assert start["uri"].startswith("otpauth://totp/") and "<svg" in (start["qr_svg"] or "<svg")
    secret = start["secret"].replace(" ", "")
    assert c.post("/admin/api/2step/confirm", json={"code": "123456"}, headers=H(tok)).status_code == 400
    codes = c.post("/admin/api/2step/confirm", json={"code": security.code_at(secret)}, headers=H(tok)).json()["backup_codes"]
    assert len(codes) == 8
    assert c.get("/admin/api/me", headers=H(tok)).json()["two_step"] is True
    # next login: the password alone is not enough
    r = login().json()
    assert r.get("need_code") and "token" not in r
    assert c.post("/admin/api/login/code", json={"ticket": r["ticket"], "code": "000000"}).status_code == 401
    r = login().json()
    used = c.post("/admin/api/login/code", json={"ticket": r["ticket"], "code": security.code_at(secret, time.time() + 30)})
    assert used.status_code == 200 and used.json()["token"]
    # a backup code works once
    r = login().json()
    ok = c.post("/admin/api/login/code", json={"ticket": r["ticket"], "code": codes[0]}).json()
    assert ok["token"] and ok["backup_left"] == 7
    r = login().json()
    assert c.post("/admin/api/login/code", json={"ticket": r["ticket"], "code": codes[0]}).status_code == 401
    # the code never lands in the audit log
    rows = main.db.all("SELECT details FROM admin_audit WHERE path LIKE '/admin/api/login/code%'")
    assert rows and all(codes[0] not in (x["details"] or "") for x in rows)


def test_required_two_step_for_the_team(setup):
    c, main, login = setup
    tok = login().json()["token"]
    assert c.put("/admin/api/security/require-2step", json={"on": True}, headers=H(tok)).status_code == 400   # own first
    secret = c.post("/admin/api/2step/start", headers=H(tok)).json()["secret"].replace(" ", "")
    c.post("/admin/api/2step/confirm", json={"code": security.code_at(secret)}, headers=H(tok))
    pw = c.post("/admin/api/team", json={"email": "s@dhurina.in", "name": "S", "role": "safety"}, headers=H(tok)).json()["temp_password"]
    assert c.put("/admin/api/security/require-2step", json={"on": True}, headers=H(tok)).json()["require_2step"]
    t2 = login(email="s@dhurina.in", pw=pw).json()["token"]
    c.post("/admin/api/password", json={"current_password": pw, "new_password": "Safety2026x"}, headers=H(t2))
    t2 = login(email="s@dhurina.in", pw="Safety2026x").json()["token"]
    assert c.get("/admin/api/me", headers=H(t2)).json()["needs_2step"] is True
    r = c.get("/admin/api/security", headers=H(t2))
    assert r.status_code == 403 and "2-step" in r.json()["detail"]
    assert c.post("/admin/api/2step/start", headers=H(t2)).status_code == 200


def test_sessions_end_others_and_logout(setup):
    c, main, login = setup
    a = login(ua=UA1).json()["token"]
    b = login(ua=UA2, ip="198.51.100.7").json()["token"]
    assert c.get("/admin/api/me", headers=H(b)).status_code == 200
    page = c.get("/admin/api/security", headers=H(a)).json()
    assert len(page["my_sessions"]) == 2 and sum(s["this"] for s in page["my_sessions"]) == 1
    assert c.post("/admin/api/sessions/end-others", headers=H(a)).json()["ended"] == 1
    assert c.get("/admin/api/me", headers=H(b)).status_code == 401
    c.post("/admin/api/logout", headers=H(a))
    assert c.get("/admin/api/me", headers=H(a)).status_code == 401


def test_login_from_a_new_place_raises_an_alert(setup):
    c, main, login = setup
    login()
    login()   # same place: no alert
    assert not main.db.one("SELECT 1 FROM alerts WHERE kind = 'new_login'")
    login(ip="198.51.100.9", ua=UA2)
    a = main.db.one("SELECT title, body FROM alerts WHERE kind = 'new_login'")
    assert a and "owner@dhurina.in" in a["title"] and "198.51.100.9" in a["body"]


def test_block_list(setup):
    c, main, login = setup
    tok = login().json()["token"]
    main.otp.sms_sender = lambda phone, msg: None
    main.db.execute("INSERT INTO teachers (id, name) VALUES ('demo', 'Demo Sir')")
    assert c.post("/admin/api/security/block", json={"kind": "ip", "value": "203.0.113.1", "reason": "x"},
                  headers=H(tok)).status_code == 400   # your own IP
    r = c.post("/admin/api/security/block", json={"kind": "phone", "value": "9876500001", "reason": "OTP flood"}, headers=H(tok))
    assert r.json()["blocks"][0]["value"] == "+919876500001"
    s = c.post("/auth/otp", json={"phone": "9876500001"}, headers={"X-Teacher-Id": "demo", "X-Forwarded-For": "192.0.2.5"})
    assert s.status_code == 403
    c.post("/admin/api/security/block", json={"kind": "ip", "value": "192.0.2.66", "reason": "bot"}, headers=H(tok))
    assert c.get("/teacher", headers={"X-Teacher-Id": "demo", "X-Forwarded-For": "192.0.2.66"}).status_code == 403
    ip_row = [b for b in security.blocks(main.db) if b["kind"] == "ip"][0]
    assert ip_row["until"] and ip_row["until"] - time.time() > 23 * 3600   # IP blocks end by themselves
    c.delete(f"/admin/api/security/block/{ip_row['id']}", headers=H(tok))
    assert c.get("/teacher", headers={"X-Teacher-Id": "demo", "X-Forwarded-For": "192.0.2.66"}).status_code == 200


def test_student_logout_everywhere(setup):
    c, main, login = setup
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    main.db.execute("INSERT INTO teachers (id, name) VALUES ('demo', 'Demo Sir')")
    hd = {"X-Teacher-Id": "demo"}

    def student_login(ip):
        c.post("/auth/otp", json={"phone": "9876500002"}, headers={**hd, "X-Forwarded-For": ip})
        code = re.search(r"\d{6}", sent[-1]).group()
        return c.post("/auth/verify", json={"phone": "9876500002", "code": code}, headers=hd).json()["token"]
    phone1 = student_login("192.0.2.10")
    time.sleep(0)   # a second phone
    main.db.execute("DELETE FROM rate_events")
    phone2 = student_login("192.0.2.11")
    new = c.post("/me/logout-all", headers={**hd, "Authorization": "Bearer " + phone1}).json()["token"]
    assert c.get("/me", headers={**hd, "Authorization": "Bearer " + phone2}).status_code == 401
    assert c.get("/me", headers={**hd, "Authorization": "Bearer " + new}).status_code == 200


def test_security_headers(setup):
    c, main, login = setup
    r = c.get("/health")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    page = c.get("/admin")
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert c.get("/health", headers={"X-Forwarded-Proto": "https"}).headers.get("strict-transport-security")


def test_ip_request_ceiling():
    lim = security.IpLimiter(3)
    assert all(lim.allow("1.2.3.4", 100 + i) for i in range(3))
    assert not lim.allow("1.2.3.4", 103) and lim.allow("5.6.7.8", 103)
    assert lim.allow("1.2.3.4", 161)   # a minute later


def test_otp_spike_alert(setup):
    c, main, login = setup
    now = time.time()
    main.db.execute("INSERT INTO rate_events (key, at) VALUES " + ",".join(["('otp:phone:demo:+91', ?)"] * 100),
                    tuple([now] * 100))
    main.alerts.periodic(main.db, main.admin.get_settings(main.db), now=now)
    assert main.db.one("SELECT 1 FROM alerts WHERE kind = 'otp_spike'")
