"""A8 · Safety test lab: the cases, the rules run, the live run's scoring and the launch gate."""
import types

import pytest

from app import safety_lab
from app.services.llm import FakeLLM


def test_cases_cover_the_brief_and_four_languages():
    cases = safety_lab.load_cases()["cases"]
    assert len(cases) >= 150
    cats = {c["category"] for c in cases}
    for need in ["sexual", "adult", "violence", "crime", "explosives", "drugs", "self_harm", "bullying", "jailbreak",
                 "privacy", "off_topic", "answer", "repeated_bypass", "unsafe", "study"]:
        assert need in cats, need
    assert {c["lang"] for c in cases} == {"en", "hi", "hi-Latn", "pa"}
    assert len({c["id"] for c in cases}) == len(cases)


def test_rules_mode_passes():
    res = safety_lab.run("rules", None)
    assert res["passed"], safety_lab.report_md(res)


class Oracle:
    """A stand-in safety model: answers what the case file expects (or, if broken, lets everything through)."""

    def __init__(self, cases, broken=False):
        self.by_text = {c["text"]: c for c in cases if "text" in c}
        for c in cases:
            for msg in c.get("sequence", []):
                self.by_text.setdefault(msg, {"expect": "block"})
        self.broken = broken

    def chat_json(self, system, user):
        c = self.by_text.get(user.strip())
        if self.broken or c is None or c["expect"] in ("allow", "off_topic", "answer"):
            return {"category": "none", "severity": "none"}
        if c["expect"] == "care":
            return {"category": "self_harm", "severity": "serious"}
        if c["expect"] == "redirect":
            return {"category": "harassment", "severity": "minor"}
        return {"category": "weapons", "severity": "serious"}


class Teacher(FakeLLM):
    """A stand-in AI teacher: steers off-topic chat back, answers facts."""

    def __init__(self, cases):
        super().__init__()
        self.cases = {c["text"]: c for c in cases if "text" in c}

    def chat_json(self, system, user):
        if "search keywords" in system:
            return {"query": "x"}
        for text, c in self.cases.items():
            if f"Student's question: {text}" in user:
                if c["expect"] == "off_topic":
                    return {"scope": "off_topic", "answer": "", "follow_up": ""}
                if c["expect"] == "answer":
                    return {"scope": "study", "answer": f"The answer is {c['must_include_any'][0]}.", "follow_up": ""}
        return {"scope": "study", "answer": "Let us study.", "follow_up": ""}


def _live(monkeypatch, broken=False):
    from app import ai_setup
    cases = safety_lab.load_cases()["cases"]
    real_build = ai_setup.build

    def build(db, settings, provider=None, switch_db=None):
        ai = real_build(db, settings, provider, switch_db)
        ai.moderator.provider, ai.moderator.llm = "llm", Oracle(cases, broken)
        teacher = Teacher(cases)
        ai.raw_llm.models = [("", teacher)]
        ai.side_llm.models = [("", teacher)]
        return ai
    monkeypatch.setattr(ai_setup, "build", build)
    s = types.SimpleNamespace(llm_api_key="", llm_base_url="", llm_model="", llm_small_model="", llm_backup_model="",
                              moderation_provider="llm")
    return safety_lab.run("live", s, "llm")


def test_live_mode_scores_a_good_safety_model_as_pass(monkeypatch):
    res = _live(monkeypatch)
    assert res["passed"], safety_lab.report_md(res)
    assert set(res["groups"]) >= {"harmful_stopped", "care_given", "study_allowed", "unsafe_output_stopped",
                                  "answers_correct", "off_topic_redirected", "bypass_stopped", "off_topic_not_punished"}


def test_live_mode_fails_a_model_that_lets_harm_through(monkeypatch):
    res = _live(monkeypatch, broken=True)
    assert not res["passed"]
    assert not res["groups"]["harmful_stopped"]["ok"] and not res["groups"]["care_given"]["ok"]
    md = safety_lab.report_md(res)
    assert "FAILED" in md and "| explosives-hi-01 |" not in md   # the phrase rules still catch that one
    assert "drugs-en-01" in md                                     # … but not this one: the model must


def test_launch_gate(tmp_path):
    from app.db import Database
    db = Database(str(tmp_path / "g.db"))
    s = types.SimpleNamespace(llm_api_key="k", llm_base_url="", llm_model="m", llm_small_model="", llm_backup_model="",
                              moderation_provider="auto")
    st = safety_lab.launch_status(s, db)
    assert st["state"] == "blocked" and "Not tested" in st["why"]
    res = {"mode": "live", "passed": True, "total": 1, "failed": 0, "groups": {}, "failures": [], "seconds": 1}
    safety_lab.save_run(db, res, "llm", "m", st["fingerprint"], "p", "admin")
    assert safety_lab.launch_status(s, db)["state"] == "ready"
    from app.services import admin
    admin.save_settings(db, {"ai": {"blocked_topics": ["gambling"]}})      # rules changed → must be tested again
    assert safety_lab.launch_status(s, db)["state"] == "blocked"
    s.llm_api_key = ""
    assert "No AI key" in safety_lab.launch_status(s, db)["why"]
