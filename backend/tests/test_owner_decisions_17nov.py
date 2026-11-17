"""Owner decisions of 17 Nov 2026: OpenAI's free moderation check by default; teachers also see flagged students."""
import importlib
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app import ai_setup  # noqa: E402


def cfg(**kw):
    base = dict(moderation_provider="auto", llm_api_key="", llm_base_url="https://api.openai.com/v1",
                openai_moderation_key="")
    return SimpleNamespace(**{**base, **kw})


def test_auto_picks_free_openai_check_when_there_is_an_openai_key():
    assert ai_setup.resolve_provider(cfg(llm_api_key="sk-x")) == "openai"
    assert ai_setup.resolve_provider(cfg(llm_api_key="k", llm_base_url="https://other.ai/v1")) == "llm"
    assert ai_setup.resolve_provider(cfg(llm_api_key="k", llm_base_url="https://other.ai/v1",
                                         openai_moderation_key="sk-m")) == "openai"
    assert ai_setup.resolve_provider(cfg()) == "rules"
    assert ai_setup.resolve_provider(cfg(llm_api_key="sk-x", moderation_provider="llm")) == "llm"   # can switch back


def test_openai_check_uses_its_own_key_and_address(tmp_path):
    from app.db import Database
    s = SimpleNamespace(moderation_provider="auto", llm_api_key="k", llm_base_url="https://other.ai/v1",
                        openai_moderation_key="sk-m", llm_model="m", llm_small_model="", llm_backup_model="")
    ai = ai_setup.build(Database(str(tmp_path / "x.db")), s)
    assert ai.provider == "openai" and ai.moderator.api_key == "sk-m"
    assert ai.moderator.base_url == "https://api.openai.com/v1"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("TEACHER_KEY_DEMO", "demo-key")
    monkeypatch.setenv("TEACHER_KEY_OTHER", "other-key")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    db = main.db
    for tid in ("demo", "other"):
        db.execute("INSERT INTO teachers (id, name) VALUES (?, ?)", (tid, tid.title()))
    mine = db.execute("INSERT INTO students (teacher_id, phone, name) VALUES ('demo', '9000000001', 'Ravi')").lastrowid
    theirs = db.execute("INSERT INTO students (teacher_id, phone, name) VALUES ('other', '9000000002', 'Amit')").lastrowid
    from app.services import student_safety
    for sid, tid in ((mine, "demo"), (theirs, "other")):
        student_safety.record_violation(db, sid, tid, "minor", "harassment", "tu pagal hai", None,
                                        student_safety.safety_settings(main.admin.get_settings(db)))
    c = TestClient(main.app)
    c.headers.update({"X-Teacher-Id": "demo", "X-Teacher-Key": "demo-key"})
    return c, main, mine, theirs


def test_teacher_sees_own_flagged_students_only_and_each_look_is_logged(setup):
    c, main, mine, theirs = setup
    lst = c.get("/teacher/safety?status=all").json()
    assert [s["name"] for s in lst["items"]] == ["Ravi"] and lst["items"][0]["violations"] == 1
    d = c.get(f"/teacher/safety/{mine}").json()
    assert d["violations"][0]["question"] == "tu pagal hai"
    assert c.get(f"/teacher/safety/{theirs}").status_code == 404     # another app's student: never
    assert c.get("/teacher/safety", headers={"X-Teacher-Key": "wrong"}).status_code == 403
    logged = main.db.all("SELECT who, path FROM admin_audit WHERE path LIKE '/teacher/safety/%'")
    assert [(r["who"], r["path"]) for r in logged] == [("teacher:demo", f"/teacher/safety/{mine}"),
                                                       ("teacher:demo", f"/teacher/safety/{theirs}")]
