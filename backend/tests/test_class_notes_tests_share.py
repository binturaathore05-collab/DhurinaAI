"""Whole-class notes, the test series, and share links."""
import json
import os
import random
import re
import sqlite3

import pytest

from app.db import Database
from app.i18n import t
from app.services import accounts, admin, classroom, notes_pdf, quiz, share
from app.services.knowledge import KnowledgeBase
from app.services.llm import FakeLLM
from app.services.tutor import TeacherProfile, Tutor

TEACHER = TeacherProfile("subhash", "Subhash Sir", "Rajasthan History")
T0 = 1_800_000_000.0


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    d.execute("INSERT INTO teachers (id, name, subject) VALUES ('subhash', 'Subhash Sir', 'Rajasthan History')")
    return d


def fake_render(html_text, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(html_text)


def chat(db, sid, session, question, reply):
    llm = FakeLLM([{"query": "x"}, reply])
    return Tutor(db, KnowledgeBase(db), llm).answer(sid, TEACHER, question, session)


def a_class(db, now=T0):
    """Hello → two study topics → thanks → an off-topic question."""
    sid = accounts.get_or_create_student(db, "subhash", "+919876543210")
    s = classroom.current_session(db, sid, "subhash", now)
    chat(db, sid, s, "Hello sir", {"answer": "Namaste beta!", "topic": "", "notes_worthy": False, "language": "hi-Latn"})
    chat(db, sid, s, "Maharana Pratap ki mrityu kab hui?",
         {"answer": "Maharana Pratap ki mrityu 19 January 1597 ko Chavand mein hui.", "topic": "Maharana Pratap",
          "notes_worthy": True, "language": "hi-Latn"})
    chat(db, sid, s, "Haldighati ka yudh kab hua?",
         {"answer": "Haldighati ka yudh 1576 mein hua.", "topic": "Haldighati ka yudh", "notes_worthy": True,
          "language": "hi-Latn"})
    chat(db, sid, s, "Thank you sir", {"answer": "Welcome!", "topic": "", "notes_worthy": False, "language": "hi-Latn"})
    chat(db, sid, s, "koi movie batao", {"scope": "off_topic", "answer": "x", "language": "hi-Latn"})
    return sid, s


# ---------- sessions ----------

def test_session_continues_then_starts_fresh_after_end_or_idle(db):
    sid = accounts.get_or_create_student(db, "subhash", "+919876543210")
    s1 = classroom.current_session(db, sid, "subhash", T0)
    assert classroom.current_session(db, sid, "subhash", T0 + 600) == s1
    assert classroom.current_session(db, sid, "subhash", T0 + 600 + classroom.IDLE_SECONDS + 1) != s1
    s3 = classroom.current_session(db, sid, "subhash", T0 + 10_000)
    classroom.end_session(db, sid, T0 + 10_001)
    assert classroom.current_session(db, sid, "subhash", T0 + 10_002) != s3


# ---------- class notes ----------

def test_topics_leave_out_greetings_small_talk_and_redirects(db):
    sid, s = a_class(db)
    assert [x["topic"] for x in classroom.session_topics(db, sid, s)] == ["Maharana Pratap", "Haldighati ka yudh"]


def test_class_notes_one_pdf_for_the_whole_class_and_only_study_content(db, tmp_path):
    sid, s = a_class(db)
    llm = FakeLLM([{"title": "Maharana Pratap aur Haldighati", "sections": [
        {"heading": "Maharana Pratap", "points": ["Mrityu: 19 January 1597, Chavand"], "summary": ""},
        {"heading": "Haldighati ka yudh", "points": ["1576 mein hua"], "summary": "Yaad rakho: 1576"}]}])
    note = classroom.save_class_notes(db, llm, sid, "Subhash Sir", str(tmp_path), s, renderer=fake_render)
    assert note["kind"] == "class" and note["topics"] == ["Maharana Pratap", "Haldighati ka yudh"]
    given = llm.calls[-1][1]
    assert "Haldighati" in given and "Namaste" not in given and "Welcome" not in given and "movie" not in given
    assert "Hinglish" in llm.calls[-1][0]  # written in the class language
    html_text = open(db.one("SELECT pdf_path FROM saved_notes WHERE id = ?", (note["id"],))["pdf_path"]).read()
    assert "Haldighati ka yudh" in html_text and "Yaad rakho" in html_text


def test_saving_again_in_the_same_class_updates_the_same_note(db, tmp_path):
    sid, s = a_class(db)
    first = classroom.save_class_notes(db, FakeLLM(), sid, "Sir", str(tmp_path), s, renderer=fake_render)
    old_path = db.one("SELECT pdf_path FROM saved_notes WHERE id = ?", (first["id"],))["pdf_path"]
    chat(db, sid, s, "Chetak kaun tha?", {"answer": "Chetak Maharana Pratap ka ghoda tha.", "topic": "Chetak",
                                          "notes_worthy": True, "language": "hi-Latn"})
    second = classroom.save_class_notes(db, FakeLLM(), sid, "Sir", str(tmp_path), s, renderer=fake_render)
    assert second["id"] == first["id"] and second["updated"] and "Chetak" in second["topics"]
    assert db.one("SELECT COUNT(*) AS n FROM saved_notes")["n"] == 1
    assert not os.path.exists(old_path)


def test_student_can_choose_topics(db, tmp_path):
    sid, s = a_class(db)
    llm = FakeLLM()
    note = classroom.save_class_notes(db, llm, sid, "Sir", str(tmp_path), s, ["haldighati ka yudh"], renderer=fake_render)
    assert note["topics"] == ["Haldighati ka yudh"] and "Maharana Pratap ki mrityu" not in llm.calls[-1][1]


def test_notes_still_made_when_ai_fails(db, tmp_path):
    class Broken:
        def chat_json(self, *_):
            raise TimeoutError
    sid, s = a_class(db)
    note = classroom.save_class_notes(db, Broken(), sid, "Sir", str(tmp_path), s, renderer=fake_render)
    html_text = open(db.one("SELECT pdf_path FROM saved_notes WHERE id = ?", (note["id"],))["pdf_path"]).read()
    assert "19 January 1597" in html_text and "Namaste" not in html_text


def test_nothing_to_save_from_only_greetings(db, tmp_path):
    sid = accounts.get_or_create_student(db, "subhash", "+919876543210")
    s = classroom.current_session(db, sid, "subhash", T0)
    chat(db, sid, s, "hi", {"answer": "Hello!", "topic": "", "notes_worthy": False})
    with pytest.raises(classroom.ClassError):
        classroom.save_class_notes(db, FakeLLM(), sid, "Sir", str(tmp_path), s, renderer=fake_render)


def test_history_shows_answers_inside_class_notes_as_saved(db, tmp_path):
    sid, s = a_class(db)
    classroom.save_class_notes(db, FakeLLM(), sid, "Sir", str(tmp_path), s, renderer=fake_render)
    hist = {h["question"]: h["pdf_saved"] for h in notes_pdf.list_history(db, sid)["items"]}
    assert hist["Haldighati ka yudh kab hua?"] and not hist["Hello sir"] and not hist["koi movie batao"]


def test_old_saved_notes_table_is_upgraded_keeping_notes(tmp_path):
    path = str(tmp_path / "old.db")
    Database(path)  # create, then make saved_notes look like the old version
    con = sqlite3.connect(path)
    con.executescript("""
        DROP TABLE saved_notes;
        CREATE TABLE saved_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
            qa_id INTEGER NOT NULL, title TEXT NOT NULL, pdf_path TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE (student_id, qa_id));
        INSERT INTO teachers (id, name) VALUES ('x', 'X');
        INSERT INTO students (id, teacher_id, phone) VALUES (1, 'x', '1');
        INSERT INTO qa_history (id, student_id, question, answer, origin, language) VALUES (5, 1, 'q', 'a', 'general_ai', 'en');
        INSERT INTO saved_notes (student_id, qa_id, title, pdf_path) VALUES (1, 5, 'Old note', '/x.pdf');""")
    con.commit(); con.close()
    d = Database(path)
    row = d.one("SELECT * FROM saved_notes")
    assert row["title"] == "Old note" and row["kind"] == "answer" and row["qa_id"] == 5
    d.execute("INSERT INTO saved_notes (student_id, qa_id, title, pdf_path, kind) VALUES (1, NULL, 'c', '/c', 'class')")


# ---------- test series ----------

def mcq_questions(n=10):
    return {"questions": [{"q": f"Q{i}?", "options": [f"right{i}", f"w{i}a", f"w{i}b", f"w{i}c"], "answer": 0,
                           "explain": f"because {i}", "topic": "Haldighati ka yudh" if i % 2 else "Maharana Pratap"}
                          for i in range(n)]}


def make_mcq(db, sid, s):
    return quiz.create_test(db, FakeLLM([mcq_questions()]), sid, "subhash", "Subhash Sir", "mcq", s,
                            rng=random.Random(1))


def test_mcq_test_hides_answers_and_shuffles_options(db):
    sid, s = a_class(db)
    view = make_mcq(db, sid, s)
    assert view["total"] == 10 and view["index"] == 0 and set(view["question"]) == {"q", "options"}
    stored = json.loads(db.one("SELECT questions FROM tests WHERE id = ?", (view["id"],))["questions"])
    assert any(q["answer"] != 0 for q in stored)  # right answer not always first


def _answer_all(db, sid, test_id, right: int):
    stored = json.loads(db.one("SELECT questions FROM tests WHERE id = ?", (test_id,))["questions"])
    out = None
    for i, q in enumerate(stored):
        choice = q["answer"] if i < right else (q["answer"] + 1) % 4
        out = quiz.answer_question(db, FakeLLM(), sid, test_id, "ABCD"[choice], "Subhash Sir")
    return out


def test_high_score_gets_shabash(db):
    sid, s = a_class(db)
    view = make_mcq(db, sid, s)
    out = _answer_all(db, sid, view["id"], right=9)
    res = out["test"]["result"]
    assert out["test"]["status"] == "done" and res["outcome"] == "praise" and res["percent"] == 90
    assert res["message"].startswith("Shabash") and "9/10" in res["message"]


def test_low_score_offers_to_teach_again_then_yes_or_no(db):
    sid, s = a_class(db)
    view = make_mcq(db, sid, s)
    res = _answer_all(db, sid, view["id"], right=3)["test"]["result"]
    assert res["outcome"] == "reteach_offer" and res["percent"] == 30 and "dobara padhaun" in res["message"]
    assert set(res["weak_topics"]) == {"Maharana Pratap", "Haldighati ka yudh"}
    request = quiz.reteach(db, sid, view["id"], True)
    assert request.startswith("Sir, please ye dobara") and "Haldighati" in request
    assert quiz.reteach(db, sid, view["id"], False) is None


def test_middle_score_is_good_with_topics_to_revise(db):
    sid, s = a_class(db)
    res = _answer_all(db, sid, make_mcq(db, sid, s)["id"], right=6)["test"]["result"]
    assert res["outcome"] == "good" and "dohra" in res["message"]


def test_each_mcq_answer_says_right_or_wrong_with_reason(db):
    sid, s = a_class(db)
    view = make_mcq(db, sid, s)
    stored = json.loads(db.one("SELECT questions FROM tests WHERE id = ?", (view["id"],))["questions"])
    r = quiz.answer_question(db, FakeLLM(), sid, view["id"], stored[0]["answer"], "Sir")
    assert r["correct"] and r["feedback"] == "because 0" and r["correct_answer"] == "right0"
    assert r["test"]["index"] == 1
    with pytest.raises(quiz.TestError):
        quiz.answer_question(db, FakeLLM(), sid, view["id"], "Z", "Sir")


def test_written_and_oral_answers_are_checked_by_sir(db):
    sid, s = a_class(db)
    gen = {"questions": [{"q": f"Explain {i}", "answer": f"model {i}", "points": ["p1", "p2"], "topic": "Maharana Pratap"}
                         for i in range(10)]}
    for mode in ("written", "oral"):
        view = quiz.create_test(db, FakeLLM([gen]), sid, "subhash", "Sir", mode, s)
        assert "options" not in view["question"]
        grader = FakeLLM([{"score": 0.5, "feedback": "Aadha sahi"}])
        r = quiz.answer_question(db, grader, sid, view["id"], "kuch points", "Sir")
        assert r["score"] == 0.5 and not r["correct"] and r["feedback"] == "Aadha sahi"
        assert "model 0" in grader.calls[-1][1]
        assert quiz.answer_question(db, FakeLLM(), sid, view["id"], "", "Sir")["score"] == 0  # skipped


def test_grading_failure_does_not_skip_the_question(db):
    class Broken:
        def chat_json(self, *_):
            raise TimeoutError
    sid, s = a_class(db)
    gen = {"questions": [{"q": f"Q{i}", "answer": "m", "points": [], "topic": "x"} for i in range(5)]}
    view = quiz.create_test(db, FakeLLM([gen]), sid, "subhash", "Sir", "written", s)
    with pytest.raises(quiz.TestError):
        quiz.answer_question(db, Broken(), sid, view["id"], "answer", "Sir")
    assert quiz.public_view(quiz._load(db, sid, view["id"]))["index"] == 0


def test_bad_questions_from_the_ai_are_dropped(db):
    sid, s = a_class(db)
    bad = {"questions": [{"q": "only two options", "options": ["a", "b"], "answer": 0},
                         {"q": "same options", "options": ["a", "a", "a", "a"], "answer": 0}]}
    with pytest.raises(quiz.TestError):
        quiz.create_test(db, FakeLLM([bad]), sid, "subhash", "Sir", "mcq", s)


def test_no_test_before_studying(db):
    sid = accounts.get_or_create_student(db, "subhash", "+919876543210")
    with pytest.raises(quiz.TestError):
        quiz.create_test(db, FakeLLM(), sid, "subhash", "Sir", "mcq", None)


def test_test_uses_the_last_class_when_asked_in_a_new_one(db):
    sid, s = a_class(db)
    new = classroom.current_session(db, sid, "subhash", T0 + 99_999)
    llm = FakeLLM([mcq_questions()])
    view = quiz.create_test(db, llm, sid, "subhash", "Sir", "mcq", new)
    assert "Haldighati" in llm.calls[-1][1] and view["total"] == 10


def test_question_count_and_limits_come_from_admin_settings(db):
    admin.save_settings(db, {"tests": {"questions": 5, "praise_from": 100}})
    sid, s = a_class(db)
    view = quiz.create_test(db, FakeLLM([mcq_questions()]), sid, "subhash", "Sir", "mcq", s)
    assert view["total"] == 5


def test_test_commands_in_many_languages():
    for text in ("Sir test lo", "sir mera test le lo", "सर टेस्ट लो", "ਸਰ ਟੈਸਟ ਲਓ", "Please test me"):
        assert quiz.is_test_command(text)
    assert not quiz.is_test_command("What is a test tube?")
    assert not quiz.is_test_command("what does test mean?")
    assert quiz.is_test_command("Sir, mera test le lo!")


def test_result_messages_exist_in_each_language():
    for key in ("test_praise", "test_good", "test_reteach_offer", "reteach_request"):
        for code in ("en", "hi", "hi-Latn", "pa"):
            assert t(key, code, teacher="S", score="1/2", pct=50, topics="x")


# ---------- share ----------

def test_share_url_and_play_store_link_validation():
    assert share.share_url("https://liveteach.in/", "subhash") == "https://liveteach.in/t/subhash"
    assert share.share_url("", "subhash", "http://localhost:8000/") == "http://localhost:8000/t/subhash"
    assert share.clean_play_store_url("com.dhurina.subhash") == \
        "https://play.google.com/store/apps/details?id=com.dhurina.subhash"
    assert share.clean_play_store_url("") == ""
    for bad in ("https://evil.example/x", "javascript:alert(1)", "http://play.google.com/store/apps/details?id=a.b"):
        with pytest.raises(ValueError):
            share.clean_play_store_url(bad)


def test_share_page_escapes_and_shows_button_only_with_store_link():
    page = share.share_page_html({"name": "<b>Sir</b>", "subject": "History", "brand_color": "red;}",
                                  "play_store_url": "", "avatar_url": "javascript:x"})
    assert "&lt;b&gt;Sir" in page and "coming to Google Play soon" in page
    assert "javascript:" not in page and "red;}" not in page
    page = share.share_page_html({"name": "Sir", "play_store_url": "https://play.google.com/store/apps/details?id=a.b"})
    assert 'href="https://play.google.com/store/apps/details?id=a.b"' in page


def test_admin_rejects_a_wrong_play_store_link(db):
    with pytest.raises(admin.AdminError):
        admin.save_teacher(db, {"id": "subhash", "name": "Subhash Sir", "play_store_url": "https://bit.ly/x"}, False)
    d = admin.save_teacher(db, {"id": "subhash", "name": "Subhash Sir", "play_store_url": "com.dhurina.subhash"}, False)
    assert d["play_store_url"].endswith("id=com.dhurina.subhash")


# ---------- on the call, and fewer AI calls without losing features ----------

def test_notes_and_test_can_be_asked_for_on_the_call():
    from app.services.tutor import is_save_command
    for text in ("सर मुझे इसके नोट्स प्रोवाइड कर दो", "Sir notes de do", "Sir, save this", "ਸਰ ਨੋਟਸ ਦੇ ਦਿਓ"):
        assert is_save_command(text), text
    assert not is_save_command("What are musical notes?")
    assert quiz.mode_in("Sir MCQ test lo") == "mcq"
    assert quiz.mode_in("सर मौखिक टेस्ट लो") == "oral" and quiz.mode_in("likhit test le lo") == "written"
    assert quiz.mode_in("Sir test lo") is None
    assert not quiz.is_test_command("How many questions do we get in the exam?")


def test_saving_unchanged_class_notes_makes_no_ai_call(db, tmp_path):
    sid, s = a_class(db)
    llm = FakeLLM()
    first = classroom.save_class_notes(db, llm, sid, "Sir", str(tmp_path), s, renderer=fake_render)
    calls = len(llm.calls)
    again = classroom.save_class_notes(db, llm, sid, "Sir", str(tmp_path), s, renderer=fake_render)
    assert again["id"] == first["id"] and again["unchanged"] and len(llm.calls) == calls
    # choosing different topics or asking something new does make new notes
    classroom.save_class_notes(db, llm, sid, "Sir", str(tmp_path), s, ["Maharana Pratap"], renderer=fake_render)
    assert len(llm.calls) == calls + 1


def test_search_keywords_are_remembered_across_students(db):
    side = FakeLLM([{"query": "Haldighati battle year"}])
    main = FakeLLM([{"answer": "1576", "follow_up": ""}, {"answer": "1576", "follow_up": ""}])
    tutor = Tutor(db, KnowledgeBase(db), main, side)
    a = accounts.get_or_create_student(db, "subhash", "+919876543210")
    b = accounts.get_or_create_student(db, "subhash", "+919876543211")
    tutor.answer(a, TEACHER, "हल्दीघाटी का युद्ध कब हुआ?")
    tutor.answer(b, TEACHER, "हल्दीघाटी का युद्ध कब हुआ ?")
    assert len(side.calls) == 1          # second student: keywords from memory
    assert len(main.calls) == 2          # but every student still gets Sir's own answer
