"""B8 · Safety policy versions: created on change with who / why, compared, verified by tests, rolled back."""
import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "v.db"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    from app.services import admin_auth
    admin_auth.create_admin(main.db, "owner@x.in", "Passw0rd1", "Owner", "owner")
    uid, tmp = admin_auth.add_member(main.db, "aud@x.in", "Aud", "auditor", "owner@x.in", {"auditor": 1})
    admin_auth.change_password(main.db, uid, tmp, "Audit2026x")
    c = TestClient(main.app)
    c.main = main
    tok = lambda e, p: c.post("/admin/api/login", json={"email": e, "password": p}).json()["token"]  # noqa: E731
    c.admin, c.aud = {"Authorization": "Bearer " + tok("owner@x.in", "Passw0rd1")}, {"Authorization": "Bearer " + tok("aud@x.in", "Audit2026x")}
    return c


def put(c, data, h=None):
    return c.put("/admin/api/settings", json=data, headers=h or c.admin)


def test_versions_track_who_why_and_only_real_changes(client):
    v = client.get("/admin/api/policy", headers=client.admin).json()
    assert len(v["items"]) == 1 and v["items"][0]["created_by"] == "system"
    put(client, {"ai": {"blocked_topics": ["politics", "adult content", "gambling"]}, "_note": "Parents asked about betting"})
    put(client, {"company": {"name": "Dhurina"}})                     # not a safety rule → no new version
    put(client, {"limits": {"questions_per_day": 400}})               # safety rule, no note
    v = client.get("/admin/api/policy", headers=client.admin).json()["items"]
    assert [x["id"] for x in v] == [3, 2, 1] and v[0]["current"]
    assert v[1]["created_by"] == "owner@x.in" and v[1]["note"] == "Parents asked about betting" and v[1]["changes"] == 1
    assert v[0]["note"] == "(no note)"


def test_compare_shows_added_removed_and_values(client):
    put(client, {"ai": {"blocked_topics": ["politics", "gambling"]}, "age_groups": {"junior": {"strictness": "medium",
                                                                                              "blocked_topics": []}}})
    d = client.get("/admin/api/policy/compare?a=1&b=2", headers=client.admin).json()
    rows = {r["key"]: r for r in d["changes"]}
    assert rows["ai.blocked_topics"]["added"] == ["gambling"] and rows["ai.blocked_topics"]["removed"] == ["adult content"]
    assert rows["age_groups.junior.strictness"]["old"] == "strict" and rows["age_groups.junior.strictness"]["new"] == "medium"
    assert rows["age_groups.junior.strictness"]["label"] == "Class 6–8: strictness"


def test_rollback_brings_back_old_rules_as_a_new_version(client):
    put(client, {"safety": {"suspend_hours": 72}, "_note": "try longer"})
    r = client.post("/admin/api/policy/1/rollback", json={"note": "too strict"}, headers=client.admin)
    assert r.status_code == 200
    from app.services import admin
    assert admin.get_settings(client.main.db)["safety"]["suspend_hours"] == 24
    top = r.json()["items"][0]
    assert top["id"] == 3 and top["rolled_back_from"] == 1 and top["note"] == "Rolled back to v1: too strict"
    assert client.post("/admin/api/policy/3/rollback", json={}, headers=client.admin).status_code == 400   # already in use
    assert client.post("/admin/api/policy/1/rollback", json={}, headers=client.aud).status_code == 403    # auditor: read only
    assert client.get("/admin/api/policy", headers=client.aud).status_code == 200
    log = client.get("/admin/api/audit", headers=client.admin).json()["items"]
    assert any(x["what"] == "Rolled the safety rules back to v1" and x["who"] == "owner@x.in" for x in log)


def test_passing_live_tests_verify_the_current_version(client):
    from app import safety_lab
    put(client, {"safety": {"suspend_hours": 48}})
    res = {"mode": "live", "passed": True, "total": 1, "failed": 0, "groups": {}, "failures": [], "seconds": 1}
    run = safety_lab.save_run(client.main.db, res, "llm", "m", "fp", "p", "settings")
    v = client.get("/admin/api/policy", headers=client.admin).json()["items"]
    assert v[0]["verified_run"] == run and not v[1]["verified_run"]
