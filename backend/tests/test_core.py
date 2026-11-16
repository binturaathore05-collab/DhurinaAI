import hashlib
import hmac
import json
import os
import re

import pytest

from app.db import Database
from app.i18n import t
from app.languages import detect_language, get_language
from app.services import accounts, notes_pdf, payments
from app.services.knowledge import KnowledgeBase, chunk_text, tokenize
from app.services.llm import FakeLLM
from app.services.tutor import TeacherProfile, Tutor, approve_answer, is_save_command, review_queue

TEACHER = TeacherProfile("subhash", "Subhash Sir", "Rajasthan History")
NOTES = ("Maharana Pratap (1540–1597) was the ruler of Mewar, born at Kumbhalgarh.\n\n"
         "The Battle of Haldighati was fought in 1576 between Maharana Pratap and Akbar's army led by Man Singh. "
         "His loyal horse was Chetak.")


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    d.execute("INSERT INTO teachers (id, name, subject) VALUES ('subhash', 'Subhash Sir', 'Rajasthan History')")
    d.execute("INSERT INTO plans (id, teacher_id, name, amount_paise, duration_days) "
              "VALUES ('y', 'subhash', 'Yearly', 99900, 365)")
    return d


def student(db, phone="+919876543210"):
    return accounts.get_or_create_student(db, "subhash", phone)


# ---------- languages ----------

def test_language_fallbacks():
    assert get_language("pa").english_name == "Punjabi"
    assert get_language("pa-IN").code == "pa"
    assert get_language("xx").code == "hi"
    assert get_language("ur").rtl


def test_detects_language_of_question():
    assert detect_language("Explain the Battle of Haldighati") == "en"
    assert detect_language("हल्दीघाटी का युद्ध कब हुआ?") == "hi"
    assert detect_language("ਮਹਾਰਾਣਾ ਪ੍ਰਤਾਪ ਕੌਣ ਸੀ?") == "pa"
    assert detect_language("மகாராணா பிரதாப் யார்?") == "ta"
    assert detect_language("Sir Haldighati ka yuddh kab hua tha?") == "hi-Latn"
    assert detect_language("Sir, Akbar ka general kaun tha? Man Singh?") == "hi-Latn"


def test_messages_in_each_language_with_english_fallback():
    assert "कोड" in t("otp_sms", "hi", code="123456", teacher="Subhash Sir")
    assert "ਕੋਡ" in t("otp_sms", "pa", code="123456", teacher="Subhash Sir")
    assert t("otp_invalid", "ta").startswith("That code")  # Tamil not yet translated -> English


# ---------- OTP ----------

def test_otp_flow(db):
    sent = []
    svc = accounts.OtpService(db, "secret", lambda phone, msg: sent.append((phone, msg)))
    svc.send("subhash", "Subhash Sir", "98765 43210")
    phone, msg = sent[0]
    assert phone == "+919876543210" and "LiveTeach code" in msg  # app is in English
    code = re.search(r"\d{6}", msg).group()
    with pytest.raises(accounts.AuthError):
        svc.verify("subhash", phone, "000000" if code != "000000" else "111111")
    assert svc.verify("subhash", phone, code) == phone
    with pytest.raises(accounts.AuthError):  # a code works only once
        svc.verify("subhash", phone, code)


def test_phone_validation():
    assert accounts.normalize_phone("+91 98765-43210") == "+919876543210"
    with pytest.raises(ValueError):
        accounts.normalize_phone("12345")


def test_token_roundtrip():
    tok = accounts.issue_token(7, "subhash", "s", 1)
    assert accounts.read_token(tok, "s") == (7, "subhash")
    with pytest.raises(accounts.AuthError):
        accounts.read_token(tok, "other")


# ---------- demo quota & subscription ----------

def test_demo_quota_then_subscription(db):
    sid = student(db)
    for _ in range(3):
        assert accounts.consume_question(db, sid, 3)
    assert not accounts.consume_question(db, sid, 3)
    assert accounts.access_status(db, sid, 3)["demo_questions_left"] == 0

    db.execute("INSERT INTO payments (student_id, plan_id, razorpay_order_id, amount_paise) VALUES (?, 'y', 'order_1', 99900)", (sid,))
    receipt = payments.mark_paid(db, "order_1", "pay_1")
    assert receipt["plan"] == "Yearly"
    payments.mark_paid(db, "order_1", "pay_1")  # webhook + app both confirm: still one subscription
    assert len(db.all("SELECT * FROM subscriptions WHERE student_id = ?", (sid,))) == 1
    assert accounts.consume_question(db, sid, 3)
    assert accounts.access_status(db, sid, 3)["subscribed"]


# ---------- knowledge base ----------

def test_tokenize_keeps_indic_words_whole():
    assert tokenize("महाराणा प्रताप का घोड़ा कौन था?") == ["महाराणा", "प्रताप", "घोड़ा"]
    assert "ਮਹਾਰਾਣਾ" in tokenize("ਮਹਾਰਾਣਾ ਪ੍ਰਤਾਪ ਦੇ ਘੋੜੇ ਦਾ ਨਾਂ ਕੀ ਸੀ?")


def test_chunking_and_search(db):
    kb = KnowledgeBase(db)
    assert len(chunk_text(" ".join(["word"] * 400))) >= 3
    kb.add_document("subhash", "Chapter 6", NOTES, "ch6", "en")
    hits = kb.search("subhash", ["Haldighati battle"])
    assert hits and "Haldighati" in hits[0].text
    assert kb.search("other-teacher", ["Haldighati"]) == []  # teachers' notes stay separate
    assert kb.search("subhash", ["photosynthesis chlorophyll"]) == []


# ---------- tutor ----------

def test_answer_from_teacher_notes_in_hindi(db):
    kb = KnowledgeBase(db)
    kb.add_document("subhash", "Chapter 6", NOTES, "ch6", "en")
    llm = FakeLLM([
        {"query": "Haldighati battle"},  # keyword rewrite of the Hindi question
        {"answer": "हल्दीघाटी का युद्ध 1576 में हुआ।", "follow_up": "चेतक कौन था?", "found_in_notes": True, "used_sources": [1], "language": "hi"},
    ])
    sid = student(db)
    ans = Tutor(db, kb, llm).answer(sid, TEACHER, "हल्दीघाटी का युद्ध कब हुआ?")
    assert ans.origin == "teacher_notes" and not ans.needs_review
    assert ans.sources[0]["title"] == "Chapter 6"
    assert ans.language == "hi"
    assert "Hindi" in llm.calls[-1][0]  # model told the student wrote in Hindi
    assert "Haldighati" in llm.calls[-1][1]  # notes were given to the model


def test_answer_in_punjabi_falls_back_to_general_ai_and_review(db):
    llm = FakeLLM([{"query": "photosynthesis"},
                   {"answer": "ਪ੍ਰਕਾਸ਼ ਸੰਸ਼ਲੇਸ਼ਣ…", "follow_up": "", "found_in_notes": False}])
    sid = student(db)
    ans = Tutor(db, KnowledgeBase(db), llm).answer(sid, TEACHER, "ਪ੍ਰਕਾਸ਼ ਸੰਸ਼ਲੇਸ਼ਣ ਕੀ ਹੈ?")
    assert ans.language == "pa"
    assert ans.origin == "general_ai" and ans.needs_review
    assert "Punjabi" in llm.calls[-1][0]
    assert ans.sources[0]["title"] == t("source_general_ai", "pa")
    queue = review_queue(db, "subhash")
    assert queue[0]["id"] == ans.qa_id

    approve_answer(db, "subhash", ans.qa_id, "Corrected answer by Sir")
    assert review_queue(db, "subhash") == []
    llm2 = FakeLLM([{"answer": "ok", "follow_up": "", "found_in_notes": True}])
    again = Tutor(db, KnowledgeBase(db), llm2).answer(sid, TEACHER, "ਪ੍ਰਕਾਸ਼ ਸੰਸ਼ਲੇਸ਼ਣ ਕੀ ਹੈ?")
    assert again.origin == "verified"
    assert "Corrected answer by Sir" in llm2.calls[-1][1]


def test_save_commands_in_many_languages():
    for phrase in ["Sir, save this", "सर इसके नोट्स सेव कर दो", "ਨੋਟਸ ਸੇਵ ਕਰ ਦਿਓ", "save as notes please"]:
        assert is_save_command(phrase), phrase
    assert not is_save_command("Explain the Battle of Haldighati")


# ---------- notes PDF & library ----------

def test_save_note_and_library(db, tmp_path):
    sid = student(db)
    llm = FakeLLM([{"query": "x"}, {"answer": "उत्तर\nदूसरी पंक्ति", "follow_up": "", "found_in_notes": False}])
    ans = Tutor(db, KnowledgeBase(db), llm).answer(sid, TEACHER, "महाराणा प्रताप कौन थे?")
    rendered = {}

    def fake_render(html_text, path):
        rendered["html"] = html_text
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(b"%PDF-fake")
        return path

    note = notes_pdf.save_note(db, sid, ans.qa_id, "Subhash Sir", str(tmp_path), renderer=fake_render)
    assert os.path.exists(note["pdf_path"])
    assert 'lang="hi"' in rendered["html"] and "Noto Sans Devanagari" in rendered["html"]
    assert "महाराणा प्रताप कौन थे?" in rendered["html"]
    assert notes_pdf.save_note(db, sid, ans.qa_id, "Subhash Sir", str(tmp_path), renderer=fake_render)["id"] == note["id"]

    lib = notes_pdf.library(db, sid)
    assert lib["saved_notes"][0]["qa_id"] == ans.qa_id
    assert lib["history"][0]["pdf_saved"] is True


def test_note_html_escapes_and_supports_rtl():
    h = notes_pdf.build_note_html("Sir", "<script>x</script>", "a", [{"title": "s"}], "ur", "2026-11-16")
    assert "<script>x" not in h and 'dir="rtl"' in h


@pytest.mark.skipif(not os.path.exists("/usr/bin/google-chrome"), reason="needs a local Chromium")
def test_real_pdf_render(tmp_path):
    h = notes_pdf.build_note_html("Subhash Sir", "Who was Maharana Pratap?", "Ruler of Mewar.", [], "en", "2026-11-16")
    out = notes_pdf.render_pdf(h, str(tmp_path / "n.pdf"), chromium_path="/usr/bin/google-chrome")
    assert open(out, "rb").read(4) == b"%PDF"


# ---------- payments ----------

def test_order_payload_splits_commission():
    p = payments.build_order_payload(99900, "r1", "acc_durina", 20)
    assert p["transfers"][0] == {"account": "acc_durina", "amount": 19980, "currency": "INR",
                                 "notes": {"purpose": "platform commission"}, "on_hold": 0}
    assert "transfers" not in payments.build_order_payload(99900, "r1", "", 20)


def test_signatures():
    sig = hmac.new(b"sec", b"order_1|pay_1", hashlib.sha256).hexdigest()
    assert payments.verify_payment_signature("order_1", "pay_1", sig, "sec")
    assert not payments.verify_payment_signature("order_1", "pay_2", sig, "sec")
    body = json.dumps({"event": "payment.captured"}).encode()
    wsig = hmac.new(b"wh", body, hashlib.sha256).hexdigest()
    assert payments.verify_webhook_signature(body, wsig, "wh")


class S:
    platform_linked_account, platform_commission_percent = "acc_durina", 20
    razorpay_key_id, razorpay_key_secret, razorpay_webhook_secret = "rzp_default", "sec", "wh"


def test_start_checkout_records_order(db):
    sid = student(db)
    seen = {}

    def fake_order(key_id, key_secret, payload):
        seen.update(payload, key_id=key_id)
        return {"id": "order_X"}

    out = payments.start_checkout(db, sid, "y", S, order_creator=fake_order)
    assert out["order_id"] == "order_X" and out["amount"] == 99900
    assert seen["transfers"][0]["amount"] == 19980  # no split set for this teacher -> default 20%
    assert db.one("SELECT status FROM payments WHERE razorpay_order_id = 'order_X'")["status"] == "created"


def test_same_student_switches_language_per_question(db):
    sid = student(db)
    llm = FakeLLM([{"query": "x"}, {"answer": "Akbar's general was Man Singh.", "found_in_notes": False},
                   {"query": "x"}, {"answer": "ਅਕਬਰ ਦਾ ਸੈਨਾਪਤੀ ਮਾਨ ਸਿੰਘ ਸੀ।", "found_in_notes": False}])
    tutor = Tutor(db, KnowledgeBase(db), llm)
    assert tutor.answer(sid, TEACHER, "Who was Akbar's general at Haldighati?").language == "en"
    assert tutor.answer(sid, TEACHER, "ਹਲਦੀਘਾਟੀ ਵਿੱਚ ਅਕਬਰ ਦਾ ਸੈਨਾਪਤੀ ਕੌਣ ਸੀ?").language == "pa"


def test_model_can_correct_detected_language(db):
    sid = student(db)  # Marathi uses the same script as Hindi; the model knows better and says so
    llm = FakeLLM([{"query": "x"}, {"answer": "हल्दीघाटीची लढाई १५७६ मध्ये झाली.", "found_in_notes": False, "language": "mr"}])
    assert Tutor(db, KnowledgeBase(db), llm).answer(sid, TEACHER, "हल्दीघाटीची लढाई कधी झाली?").language == "mr"


def test_plan_lifecycle_reminder_grace_expired_renew(db):
    import time as _t
    sid = student(db)
    now = _t.time()
    for _ in range(3):
        accounts.consume_question(db, sid, 3)
    # plan ending in 2 days -> active, renew reminder on
    db.execute("INSERT INTO subscriptions (student_id, plan_id, starts_at, ends_at) VALUES (?, 'y', ?, ?)",
               (sid, now - 28 * 86400, now + 2 * 86400 + 60))
    st = accounts.access_status(db, sid, 3, grace_days=2, grace_questions=3, reminder_days=3)
    assert st["state"] == "active" and st["days_left"] == 2 and st["renew_soon"]

    # plan ended 1 hour ago -> grace: 3 questions
    db.execute("UPDATE subscriptions SET ends_at = ? WHERE student_id = ?", (now - 3600, sid))
    st = accounts.access_status(db, sid, 3, grace_days=2, grace_questions=3)
    assert st["state"] == "grace" and st["grace_questions_left"] == 3 and st["can_ask"]
    for i in range(3):
        assert accounts.consume_question(db, sid, 3, 2, 3)
        db.execute("INSERT INTO qa_history (student_id, question, answer, origin, language) VALUES (?, ?, 'a', 'x', 'en')",
                   (sid, f"q{i}"))
    st = accounts.access_status(db, sid, 3, grace_days=2, grace_questions=3)
    assert st["state"] == "expired" and not st["can_ask"] and st["plan_ended_at"]
    assert not accounts.consume_question(db, sid, 3, 2, 3)

    # no grace configured -> straight to expired
    assert accounts.access_status(db, sid, 3)["state"] == "expired"

    # renewing activates again; library/history untouched
    db.execute("INSERT INTO payments (student_id, plan_id, razorpay_order_id, amount_paise) VALUES (?, 'y', 'order_r', 99900)", (sid,))
    payments.mark_paid(db, "order_r", "pay_r")
    st = accounts.access_status(db, sid, 3, grace_days=2, grace_questions=3)
    assert st["state"] == "active" and st["days_left"] >= 364
    assert len(db.all("SELECT * FROM qa_history WHERE student_id = ?", (sid,))) == 3


def test_early_renewal_adds_days_after_current_plan(db):
    import time as _t
    sid = student(db)
    now = _t.time()
    db.execute("INSERT INTO subscriptions (student_id, plan_id, starts_at, ends_at) VALUES (?, 'y', ?, ?)",
               (sid, now - 86400, now + 10 * 86400))
    db.execute("INSERT INTO payments (student_id, plan_id, razorpay_order_id, amount_paise) VALUES (?, 'y', 'order_e', 99900)", (sid,))
    payments.mark_paid(db, "order_e", "pay_e", now=now)
    assert accounts.access_status(db, sid, 3)["days_left"] >= 374


def test_library_pages_many_notes(db, tmp_path):
    sid = student(db)
    for i in range(250):
        cur = db.execute("INSERT INTO qa_history (student_id, question, answer, origin, language) VALUES (?, ?, 'a', 'x', 'en')",
                         (sid, f"Question {i} about Mewar" if i % 2 else f"Question {i} about Chambal"))
        db.execute("INSERT INTO saved_notes (student_id, qa_id, title, pdf_path) VALUES (?, ?, ?, 'p')",
                   (sid, cur.lastrowid, f"Question {i}"))
    lib = notes_pdf.library(db, sid)
    assert len(lib["saved_notes"]) == 10 and lib["notes_total"] == 250
    assert len(lib["history"]) == 30 and lib["history_total"] == 250 and lib["history"][0]["pdf_saved"]
    page = notes_pdf.list_notes(db, sid, offset=240, limit=20)
    assert len(page["items"]) == 10
    assert notes_pdf.library(db, sid, q="Chambal")["history_total"] == 125


def test_commission_split_is_set_per_teacher(db):
    db.execute("UPDATE teachers SET platform_commission_percent = 25, razorpay_key_id = 'rzp_subhash', "
               "razorpay_key_secret = 'sec_subhash' WHERE id = 'subhash'")
    db.execute("INSERT INTO teachers (id, name, platform_commission_percent) VALUES ('meena', 'Meena Ma’am', 30)")
    db.execute("INSERT INTO plans (id, teacher_id, name, amount_paise, duration_days) VALUES ('m', 'meena', 'Monthly', 50000, 30)")
    sid = student(db)
    sid2 = accounts.get_or_create_student(db, "meena", "+919876500000")
    seen = []

    def fake_order(key_id, key_secret, payload):
        seen.append((key_id, key_secret, payload))
        return {"id": f"order_{len(seen)}"}

    payments.start_checkout(db, sid, "y", S, order_creator=fake_order)
    payments.start_checkout(db, sid2, "m", S, order_creator=fake_order)
    (k1, s1, p1), (k2, s2, p2) = seen
    assert (k1, s1) == ("rzp_subhash", "sec_subhash") and p1["transfers"][0]["amount"] == 24975   # 25% of 999
    assert k2 == "rzp_default" and p2["transfers"][0]["amount"] == 15000                         # 30% of 500
    assert "teacher 70% / platform 30%" in p2["notes"]["split"]
    ps = payments.teacher_payment_settings(db, "subhash", S)
    assert ps["teacher_percent"] == 75 and ps["platform_percent"] == 25
    db.execute("UPDATE teachers SET platform_commission_percent = 0 WHERE id = 'meena'")
    payments.start_checkout(db, sid2, "m", S, order_creator=fake_order)
    assert "transfers" not in seen[-1][2]  # 0% commission -> no transfer at all


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE teachers (id TEXT PRIMARY KEY, name TEXT NOT NULL, subject TEXT, avatar_url TEXT, "
                "brand_color TEXT, razorpay_key_id TEXT, created_at TEXT)")
    con.commit(); con.close()
    d = Database(path)
    cols = {r["name"] for r in d.all("PRAGMA table_info(teachers)")}
    assert {"platform_commission_percent", "razorpay_key_secret", "razorpay_webhook_secret"} <= cols


# ---------- teaching style, personality, level, human-like interaction ----------
from app.services import style as style_mod  # noqa: E402


def test_style_rules_follow_teacher_settings(db):
    st = style_mod.save_style(db, "subhash", {
        "personalities": ["strict", "funny", "strict", "bogus"],
        "teaching": {"tricks": {"on": False}, "story": {"text": "Har topic ko ek Rajasthani kahani se shuru karo."}},
        "interaction": {"use_name": True}, "avatar": {"gestures": False}})
    assert st["avatar"]["gestures"] is False and st["personalities"] == ["strict", "funny"]
    rules = style_mod.style_rules(style_mod.get_style(db, "subhash"), "Rohit", "beginner")
    assert "Strict" in rules and "Funny" in rules
    assert "Rajasthani kahani" in rules and "Memory tricks" not in rules
    assert "Rohit" in rules and "BEGINNER" in rules
    style_mod.save_style(db, "subhash", {"interaction": {"use_name": False}, "personalities": ["nonsense"]})
    rules = style_mod.style_rules(style_mod.get_style(db, "subhash"), "Rohit", "advanced")
    assert "Rohit" not in rules and "Strict" in rules and "ADVANCED" in rules


def test_level_goes_up_and_down_with_answers(db):
    sid = student(db)
    assert style_mod.get_level(db, sid) == "intermediate"
    for _ in range(3):
        style_mod.record_check(db, sid, True)
    assert style_mod.get_level(db, sid) == "advanced"
    style_mod.record_check(db, sid, False)
    style_mod.record_check(db, sid, False)
    assert style_mod.get_level(db, sid) == "intermediate"


def test_tutor_returns_emotion_board_and_checks_followup_answer(db):
    sid = student(db)
    db.execute("UPDATE students SET name = 'Rohit' WHERE id = ?", (sid,))
    llm = FakeLLM([
        {"query": "x"}, {"answer": "Haldighati 1576 mein hua…", "follow_up": "Pratap ke ghode ka naam?", "found_in_notes": False,
                         "emotion": "excited", "emphasis": ["1576", "Haldighati"], "board": ["Haldighati – 1576", "Pratap vs Man Singh"]},
        {"query": "x"}, {"answer": "Shabaash Rohit! Bilkul sahi, Chetak.", "follow_up": "", "answered_follow_up": True,
                         "follow_up_correct": True, "found_in_notes": False, "emotion": "nonsense"},
    ])
    tutor = Tutor(db, KnowledgeBase(db), llm)
    a1 = tutor.answer(sid, TEACHER, "Sir Haldighati ka yuddh kab hua?")
    assert a1.emotion == "excited" and a1.board == ["Haldighati – 1576", "Pratap vs Man Singh"] and a1.emphasis == ["1576", "Haldighati"]
    a2 = tutor.answer(sid, TEACHER, "Chetak")
    assert a2.check == "correct" and a2.emotion == "smile" and not a2.needs_review
    system, user = llm.calls[-1]
    assert "Rohit" in system and "Friendly" in system           # name + default personality in the rules
    assert "You asked: Pratap ke ghode ka naam?" in user        # recent conversation is passed as context
    row = db.one("SELECT emotion, board, check_result FROM qa_history WHERE id = ?", (a1.qa_id,))
    assert row["emotion"] == "excited" and "1576" in row["board"]


def test_up_to_three_personalities_and_old_format(db):
    st = style_mod.save_style(db, "subhash", {"personalities": ["friendly", "motivational", "funny", "calm"]})
    assert st["personalities"] == ["friendly", "motivational", "funny"]
    rules = style_mod.style_rules(st, None, "intermediate")
    assert "Friendly" in rules and "Motivational" in rules and "Funny" in rules and "Calm" not in rules
    assert style_mod.save_style(db, "subhash", {"personality": "calm", "personality_2": "strict"})["personalities"] == ["calm", "strict"]
