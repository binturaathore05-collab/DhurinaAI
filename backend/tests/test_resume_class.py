"""Resume the class where the student left it (owner, 20 Nov 2026).

- Back within 30 minutes: the last question and answer are simply on the screen again (no greeting).
- Back after more than 30 minutes: Sir says what they were studying and asks: continue, or a new question?
- At least one whole day without study: Sir also talks kindly about the gap (book study is fine; daily study matters).
- Sir's words are made by the AI each time (owner choice), checked like every AI text, and fall back to a fixed,
  safe sentence when the AI or the check is not available. One greeting per return (cached), so opening the app
  again and again costs nothing extra.
"""
import importlib
import re
import time
from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.services import resume  # noqa: E402

IST = 5.5 * 3600


def ts(y, m, d, hh=12, mm=0):
    """A UTC epoch for a given UTC wall time."""
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp()


def sql_time(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------- unit: days without study ----------------

@pytest.mark.parametrize("last, now, missed", [
    (ts(2026, 11, 20, 4), ts(2026, 11, 20, 10), 0),       # same day
    (ts(2026, 11, 19, 10), ts(2026, 11, 20, 10), 0),      # yesterday → no gap
    (ts(2026, 11, 18, 10), ts(2026, 11, 20, 10), 1),      # one whole day skipped
    (ts(2026, 11, 15, 10), ts(2026, 11, 20, 10), 4),
    (ts(2026, 11, 18, 19), ts(2026, 11, 19, 19), 0),      # 00:30 IST 19th → 00:30 IST 20th = next day, no gap
    (ts(2026, 11, 18, 18), ts(2026, 11, 20, 19), 2),      # 23:30 IST 18th → 00:30 IST 21st: the 19th and 20th missed
    (ts(2026, 11, 21, 10), ts(2026, 11, 20, 10), 0),      # a clock in the future never gives a negative gap
])
def test_days_missed_counts_whole_ist_days(last, now, missed):
    assert resume.days_missed(last, now) == missed


def test_days_missed_reads_database_time_text():
    assert resume.days_missed("2026-11-18 10:00:00", ts(2026, 11, 20, 10)) == 1


# ---------------- unit: fixed (safe) sentences ----------------

@pytest.mark.parametrize("lang, word", [("hi", "आगे"), ("en", "continue"), ("pa", "ਅੱਗੇ"), ("hi-Latn", "aage")])
def test_template_in_each_language(lang, word):
    text = resume.template(lang, teacher="Gupta Sir", name="Riya", topic="Thar desert", follow_up="", days=0)
    assert word in text.lower() and "Thar desert" in text


def test_template_talks_about_the_gap_only_after_a_missed_day():
    no_gap = resume.template("hi", teacher="Gupta Sir", name="Riya", topic="भिन्न", follow_up="", days=0)
    gap = resume.template("hi", teacher="Gupta Sir", name="Riya", topic="भिन्न", follow_up="", days=3)
    assert "3" in gap and "3" not in no_gap
    assert "किताब" in gap and "किताब" not in no_gap


def test_template_handles_odd_text_and_unknown_language():
    odd = 'x" <script>alert(1)</script> ✓ प्रकाश-संश्लेषण 😀'
    text = resume.template("xx", teacher="Sir", name="", topic=odd, follow_up="", days=0)
    assert odd in text   # plain text: the app shows it as text, nothing breaks
    long_topic = "क" * 2000
    assert len(resume.template("hi", teacher="Sir", name="", topic=long_topic, follow_up="", days=0)) < 800


def test_template_mentions_sirs_open_question():
    text = resume.template("en", teacher="Sir", name="Riya", topic="Fractions", follow_up="What is 1/2 + 1/4?", days=0)
    assert "1/2 + 1/4" in text


# ---------------- unit: continue / new question phrases ----------------

@pytest.mark.parametrize("text", ["aage badhao", "Sir aage badhaiye", "आगे बढ़ाइए", "continue", "wahi continue karo",
                                  "पिछला वाला जारी रखो", "ਅੱਗੇ ਵਧਾਓ"])
def test_continue_phrases(text):
    assert resume.is_continue(text)


@pytest.mark.parametrize("text", ["haan", "photosynthesis kya hai", "", "continue kya hota hai matlab samjhao " * 3])
def test_not_continue(text):
    assert not resume.is_continue(text)


@pytest.mark.parametrize("text", ["naya sawal", "नया सवाल पूछना है", "new question", "ਨਵਾਂ ਸਵਾਲ"])
def test_new_question_phrases(text):
    assert resume.is_new(text) and not resume.is_continue(text)


def test_continue_question_keeps_the_topic_in_the_students_language():
    q = resume.continue_question("hi", "थार मरुस्थल", "थार मरुस्थल कहाँ है?")
    assert "थार मरुस्थल" in q and "आगे" in q
    assert "Thar" in resume.continue_question("en", "Thar desert", "")
    assert len(resume.continue_question("hi", "", "क" * 3000)) < 600   # very long last question is cut


# ---------------- integration: the whole flow through the server ----------------

@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name) VALUES ('demo', 'Gupta Sir')")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    c = TestClient(main.app)

    def login(phone):
        h = {"X-Teacher-Id": "demo"}
        main.db.execute("DELETE FROM rate_events")
        c.post("/auth/otp", json={"phone": phone}, headers=h)
        tok = c.post("/auth/verify", json={"phone": phone, "code": re.search(r"\d{6}", sent[-1]).group()},
                     headers=h).json()["token"]
        return {**h, "Authorization": "Bearer " + tok}
    fake = main.raw_llm.pick()
    return c, main, login, fake


def _age_history(main, sid, seconds):
    for r in main.db.all("SELECT id, created_at FROM qa_history WHERE student_id = ?", (sid,)):
        old = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        main.db.execute("UPDATE qa_history SET created_at = ? WHERE id = ?", (sql_time(old - seconds), r["id"]))


def _sid(main, h):
    return main.accounts.read_token(h["Authorization"][7:], main.settings.jwt_secret)[0]


def test_first_class_has_nothing_to_resume(setup):
    c, main, login, fake = setup
    h = login("9876500001")
    assert c.get("/class/resume", headers=h).json()["type"] == "none"


def test_back_soon_shows_the_last_answer_without_a_greeting(setup):
    c, main, login, fake = setup
    h = login("9876500001")
    a = c.post("/class/ask", json={"question": "थार मरुस्थल कहाँ है?"}, headers=h).json()
    r = c.get("/class/resume", headers=h).json()
    assert r["type"] == "recent" and r["last"]["qa_id"] == a["qa_id"] and r["last"]["answer"] == a["answer"]
    assert "greeting" not in r


def test_back_after_hours_sir_asks_continue_or_new(setup):
    c, main, login, fake = setup
    h = login("9876500001")
    c.post("/class/ask", json={"question": "थार मरुस्थल कहाँ है?"}, headers=h)
    _age_history(main, _sid(main, h), 3 * 3600)
    fake.replies = [{"greeting": "नमस्ते Riya! पिछली बार हम थार मरुस्थल पढ़ रहे थे। आगे बढ़ाएँ या नया सवाल?"}]
    r = c.get("/class/resume", headers=h).json()
    assert r["type"] == "resume" and r["source"] == "ai" and "थार" in r["greeting"]
    assert r["days_missed"] == 0 and r["topic"]
    calls = len(fake.calls)
    again = c.get("/class/resume", headers=h).json()   # opening again: the same greeting, no new AI call
    assert again["greeting"] == r["greeting"] and len(fake.calls) == calls


def test_after_days_away_sir_talks_about_the_gap(setup):
    c, main, login, fake = setup
    h = login("9876500001")
    c.post("/class/ask", json={"question": "थार मरुस्थल कहाँ है?"}, headers=h)
    _age_history(main, _sid(main, h), 4 * 86400)
    fake.replies = [{"greeting": "4 दिन बाद आए हो! किताब से पढ़ रहे थे तो अच्छा… आगे बढ़ाएँ या नया सवाल?"}]
    r = c.get("/class/resume", headers=h).json()
    assert r["days_missed"] >= 3
    prompt = fake.calls[-1][1]
    assert "days" in prompt.lower() and "book" in prompt.lower()   # the AI is told about the gap and the book


def test_continue_teaches_the_same_topic_and_counts_one_question(setup):
    c, main, login, fake = setup
    h = login("9876500001")
    c.post("/class/ask", json={"question": "थार मरुस्थल कहाँ है?"}, headers=h)
    _age_history(main, _sid(main, h), 3 * 3600)
    before = c.get("/me/access", headers=h).json()["demo_questions_left"]
    a = c.post("/class/ask", json={"question": "आगे बढ़ाइए"}, headers=h).json()
    assert a["type"] == "answer"
    q = main.db.one("SELECT question FROM qa_history ORDER BY id DESC LIMIT 1")["question"]
    assert "थार मरुस्थल" in q
    assert c.get("/me/access", headers=h).json()["demo_questions_left"] == before - 1


def test_new_question_command(setup):
    c, main, login, fake = setup
    h = login("9876500001")
    c.post("/class/ask", json={"question": "थार मरुस्थल कहाँ है?"}, headers=h)
    r = c.post("/class/ask", json={"question": "नया सवाल पूछना है"}, headers=h).json()
    assert r["type"] == "new_question" and r["message"]


def test_continue_with_nothing_to_continue_is_a_normal_question(setup):
    c, main, login, fake = setup
    h = login("9876500001")
    r = c.post("/class/ask", json={"question": "continue"}, headers=h).json()
    assert r["type"] == "answer"


def test_ai_down_or_unsafe_greeting_falls_back_to_the_fixed_sentence(setup, monkeypatch):
    c, main, login, fake = setup
    h = login("9876500001")
    c.post("/class/ask", json={"question": "थार मरुस्थल कहाँ है?"}, headers=h)
    _age_history(main, _sid(main, h), 3 * 3600)

    def boom(system, user):
        raise TimeoutError("AI timed out")
    monkeypatch.setattr(fake, "chat_json", boom)
    r = c.get("/class/resume", headers=h)
    assert r.status_code == 200 and r.json()["source"] == "template" and "थार" in r.json()["greeting"]


def test_unsafe_ai_greeting_is_never_shown(setup, monkeypatch):
    c, main, login, fake = setup
    h = login("9876500001")
    c.post("/class/ask", json={"question": "थार मरुस्थल कहाँ है?"}, headers=h)
    _age_history(main, _sid(main, h), 3 * 3600)
    fake.replies = [{"greeting": "SOMETHING UNSAFE"}]
    real = main.moderator.check

    def flag(text, stage):
        if "UNSAFE" in text:
            return main.moderation.Verdict("violence", "serious", "model")
        return real(text, stage)
    monkeypatch.setattr(main.moderator, "check", flag)
    r = c.get("/class/resume", headers=h).json()
    assert "UNSAFE" not in r["greeting"] and r["source"] == "template"


def test_resume_needs_a_valid_login_and_never_shows_another_students_class(setup):
    c, main, login, fake = setup
    a = login("9876500001")
    c.post("/class/ask", json={"question": "थार मरुस्थल कहाँ है?"}, headers=a)
    b = login("9876500002")
    assert c.get("/class/resume", headers=b).json()["type"] == "none"
    bad = {**a, "Authorization": "Bearer expired.or.wrong"}
    assert c.get("/class/resume", headers=bad).status_code == 401


def test_a_database_error_never_blocks_opening_the_class(setup, monkeypatch):
    c, main, login, fake = setup
    h = login("9876500001")
    import sqlite3

    def down(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(main.resume, "look", down)
    r = c.get("/class/resume", headers=h)
    assert r.status_code == 200 and r.json()["type"] == "none"


def test_paused_institute_can_see_the_greeting_but_not_continue(setup):
    c, main, login, fake = setup
    h = login("9876500001")
    c.post("/class/ask", json={"question": "थार मरुस्थल कहाँ है?"}, headers=h)
    _age_history(main, _sid(main, h), 3 * 3600)
    main.institute_status.change(main.db, "demo", "paused", "fees", "owner")
    r = c.get("/class/resume", headers=h)
    assert r.status_code == 200 and r.json()["source"] == "template"   # no AI money while paused
    assert c.post("/class/ask", json={"question": "आगे बढ़ाइए"}, headers=h).status_code == 403
