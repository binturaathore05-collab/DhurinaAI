"""Safety A1: education-only mode + the admin's blocked topics are enforced on every answer."""
import pytest

from app.db import Database
from app.i18n import t
from app.services import accounts, admin, notes_pdf
from app.services.knowledge import KnowledgeBase
from app.services.llm import FakeLLM
from app.services.tutor import TeacherProfile, Tutor, review_queue

TEACHER = TeacherProfile("subhash", "Subhash Sir", "Rajasthan History")


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    d.execute("INSERT INTO teachers (id, name, subject) VALUES ('subhash', 'Subhash Sir', 'Rajasthan History')")
    return d


def ask(db, replies, question, phone="+919876543210"):
    llm = FakeLLM([{"query": "x"}, *replies])
    sid = accounts.get_or_create_student(db, "subhash", phone)
    return Tutor(db, KnowledgeBase(db), llm).answer(sid, TEACHER, question), llm, sid


def test_prompt_carries_education_only_rule_and_admin_blocked_topics(db):
    admin.save_settings(db, {"ai": {"blocked_topics": ["politics", "adult content", "betting tips"]}})
    _, llm, _ = ask(db, [{"scope": "study", "answer": "1576", "follow_up": ""}], "Haldighati kab hua?")
    system = llm.calls[-1][0]
    assert "Help ONLY with studies" in system
    assert "politics; adult content; betting tips" in system
    assert '"scope"' in system


def test_admin_change_reaches_the_ai_without_restart(db):
    _, llm, _ = ask(db, [{"answer": "a", "follow_up": ""}], "q1")
    assert "betting tips" not in llm.calls[-1][0]
    admin.save_settings(db, {"ai": {"blocked_topics": ["betting tips"]}})
    _, llm, _ = ask(db, [{"answer": "a", "follow_up": ""}], "q2")
    assert "betting tips" in llm.calls[-1][0]


def test_no_blocked_topics_still_education_only(db):
    admin.save_settings(db, {"ai": {"blocked_topics": []}})
    _, llm, _ = ask(db, [{"answer": "a", "follow_up": ""}], "q")
    assert "Help ONLY with studies" in llm.calls[-1][0] and "BLOCKED" not in llm.calls[-1][0]


def test_blocked_topic_gets_fixed_redirect_never_the_model_text(db):
    ans, _, sid = ask(db, [{"scope": "blocked", "blocked_topic": "politics", "answer": "Party X is the best",
                            "follow_up": "Who do you vote for?", "board": ["vote X"], "language": "hi"}],
                      "कौन सी पार्टी सबसे अच्छी है?")
    assert ans.origin == "redirect" and ans.scope == "blocked"
    assert ans.answer == t("redirect_study", "hi")
    assert "Party X" not in ans.answer and ans.follow_up == "" and ans.board == [] and ans.sources == []
    assert not ans.needs_review and review_queue(db, "subhash") == []
    row = db.one("SELECT * FROM qa_history WHERE id = ?", (ans.qa_id,))
    assert row["origin"] == "redirect" and row["scope"] == "blocked" and row["blocked_topic"] == "politics"
    assert "Party X" not in row["answer"]  # the unsafe text is not stored either


def test_off_topic_in_hinglish_redirects_in_hinglish(db):
    ans, _, _ = ask(db, [{"scope": "off_topic", "answer": "Watch movie Y", "follow_up": "", "language": "hi-Latn"}],
                    "koi achhi movie batao")
    assert ans.origin == "redirect" and ans.scope == "off_topic"
    assert ans.answer == t("redirect_study", "hi-Latn") and ans.answer.startswith("Chalo")


def test_unknown_scope_fails_closed(db):
    ans, _, _ = ask(db, [{"scope": "maybe", "answer": "risky", "follow_up": ""}], "something")
    assert ans.origin == "redirect" and "risky" not in ans.answer


def test_study_question_is_answered_normally(db):
    ans, _, _ = ask(db, [{"scope": "study", "answer": "Haldighati 1576 mein hua.", "follow_up": "",
                          "language": "hi-Latn"}], "Haldighati kab hua?")
    assert ans.origin == "general_ai" and ans.scope == "study" and ans.answer.startswith("Haldighati")


def test_redirect_cannot_be_saved_as_notes(db, tmp_path):
    ans, _, sid = ask(db, [{"scope": "off_topic", "answer": "x", "follow_up": ""}], "cricket score?")
    with pytest.raises(KeyError):
        notes_pdf.save_note(db, sid, ans.qa_id, "Subhash Sir", str(tmp_path), renderer=lambda h, p: None)


def test_redirect_message_in_every_language_falls_back_to_english():
    for code in ("en", "hi", "hi-Latn", "pa"):
        assert t("redirect_study", code)
    assert t("redirect_study", "ta") == t("redirect_study", "en")
