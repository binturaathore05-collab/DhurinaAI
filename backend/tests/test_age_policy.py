"""B2 · Safety rules by age group: the AI teacher's instructions and the safety check follow the student's group."""
import importlib
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.services import age_policy  # noqa: E402


def test_groups_from_class_and_age():
    g = age_policy.group_of
    assert g("6", False) == "junior" and g("8", 0) == "junior" and g("9", False) == "middle"
    assert g("12", False) == "senior" and g("college", False) == "senior" and g("4", False) == "primary"
    assert g("10", True) == "adult" and g(None, None) is None


def test_validation():
    with pytest.raises(age_policy.AgePolicyError):
        age_policy.validate({"junior": {"strictness": "very"}})
    with pytest.raises(age_policy.AgePolicyError):
        age_policy.validate({"toddler": {"strictness": "strict"}})
    v = age_policy.validate({"junior": {"strictness": "medium", "blocked_topics": ["horror", " ", "romance"]},
                             "adult": {"strictness": "relaxed"}})
    assert v["junior"]["blocked_topics"] == ["horror", "romance"] and v["adult"]["blocked_topics"] == []


class Clf:
    def __init__(self):
        self.systems = []

    def chat_json(self, system, user):
        self.systems.append(system)
        return {"category": "none", "severity": "none"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "b2.db"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Teacher', 'History')")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    clf = Clf()
    main.moderator.provider, main.moderator.llm = "llm", clf
    c = TestClient(main.app)
    c.headers["X-Teacher-Id"] = "demo"
    c.post("/auth/otp", json={"phone": "9876543210"})
    code = re.search(r"\d{6}", sent[-1]).group()
    c.headers["Authorization"] = "Bearer " + c.post("/auth/verify", json={"phone": "9876543210", "code": code}).json()["token"]
    c.main, c.clf = main, clf
    return c


def _system(c):
    return [x for x in c.main.raw_llm.calls if "Return JSON only" in x[0] and "CLASS RULES" in x[0]][-1][0]


def test_class_7_student_gets_strict_rules_everywhere(client):
    client.put("/me/profile", json={"class_level": "7", "is_adult": False})
    client.post("/class/ask", json={"question": "What is puberty?"})
    s = _system(client)
    assert "young student" in s and "romance and dating" in s and "horror and gore" in s
    assert any("Class 6–8" in x and "romance or dating" in x for x in client.clf.systems)   # the safety check too


def test_adult_gets_relaxed_rules_and_no_child_topics(client):
    client.put("/me/profile", json={"class_level": "college", "is_adult": True})
    client.post("/class/ask", json={"question": "Explain the NDPS Act"})
    s = _system(client)
    assert "adult student" in s and "romance and dating" not in s
    assert any("The student is an adult" in x for x in client.clf.systems)


def test_admin_changes_apply_at_once(client):
    from app.services import admin
    admin.save_settings(client.main.db, {"age_groups": {"middle": {"strictness": "strict",
                                                                    "blocked_topics": ["cricket betting"]}}})
    client.put("/me/profile", json={"class_level": "9", "is_adult": False})
    client.post("/class/ask", json={"question": "q"})
    s = _system(client)
    assert "young student" in s and "cricket betting" in s and "dating advice" not in s


def test_same_text_checked_again_for_another_age_group(client):
    """The safety check's memory (cache) is per strictness: a 'fine for adults' verdict is not reused for a child."""
    client.put("/me/profile", json={"class_level": "college", "is_adult": True})
    client.post("/class/ask", json={"question": "Tell me about the history of wine"})
    n = len(client.clf.systems)
    client.put("/me/profile", json={"class_level": "7", "is_adult": False})
    client.post("/class/ask", json={"question": "Tell me about the history of wine"})
    assert len(client.clf.systems) > n


def test_policy_version_changes_with_age_rules(client):
    from app.services import admin, audit
    v1 = audit.policy_version(client.main.db, "p", admin.get_settings(client.main.db))
    admin.save_settings(client.main.db, {"age_groups": {"junior": {"strictness": "medium", "blocked_topics": []}}})
    assert audit.policy_version(client.main.db, "p", admin.get_settings(client.main.db)) != v1
