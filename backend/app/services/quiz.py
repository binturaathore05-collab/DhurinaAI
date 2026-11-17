"""Test series: after class (or whenever the student asks, "Sir, test lo"), Sir gives questions on what he taught.

Three ways, the student chooses:
  mcq     – 4 options, tap (or say "B"); checked instantly
  written – short written answers; Sir checks them against the key points
  oral    – Sir asks one by one like a viva; the student answers in a sentence or two (typed now, voice later)

At the end: below `reteach_below`% Sir offers to teach the weak topics again (yes / no);
from `praise_from`% Sir says shabash; in between, "good, revise these topics".
Correct answers stay on the server until the student has answered, so the app can't leak them.
"""
import json
import random
import re
import time

from ..db import Database
from ..i18n import t
from ..languages import get_language
from . import admin as admin_mod
from . import classroom
from .llm import LLM

MODES = ("mcq", "written", "oral")

TEST_PHRASES = [
    "test lo", "test le lo", "test lijiye", "test do", "take my test", "give me a test", "test me", "quiz me",
    "viva lo", "viva le lo", "sawal do", "sawal pucho", "test lena", "test start",
    "टेस्ट लो", "टेस्ट ले लो", "टेस्ट लीजिए", "टेस्ट दो", "मेरा टेस्ट", "सवाल दो", "सवाल पूछो", "प्रश्न दो",
    "ਟੈਸਟ ਲਓ", "ਟੈਸਟ ਲੈ ਲਓ", "ਮੇਰਾ ਟੈਸਟ", "ਸਵਾਲ ਦਿਓ",
]


class TestError(ValueError):
    pass


def _padded(text: str) -> str:
    return " " + re.sub(r"[^\w\u0900-\u0A7F]+", " ", text.lower()).strip() + " "


def is_test_command(text: str) -> bool:
    """Whole words only, so "what does test mean?" is a question, not a command."""
    low = _padded(text)
    return any(f" {p} " in low for p in TEST_PHRASES)


MODE_WORDS = {
    "mcq": ["mcq", "objective", "options", "एमसीक्यू", "ऑब्जेक्टिव"],
    "written": ["written", "likhit", "likh kar", "likhkar", "लिखित", "लिखकर", "लिख कर", "ਲਿਖਤੀ"],
    "oral": ["oral", "viva", "bol kar", "bolkar", "maukhik", "मौखिक", "बोलकर", "बोल कर", "वाइवा", "ਮੌਖਿਕ", "ਬੋਲ ਕੇ"],
}


def mode_in(text: str) -> str | None:
    """'Sir, MCQ test lo' / 'viva le lo' — the student named the kind of test on the call."""
    low = _padded(text)
    for mode, words in MODE_WORDS.items():
        if any(f" {w} " in low for w in words):
            return mode
    return None


def test_settings(db: Database) -> dict:
    s = admin_mod.get_settings(db).get("tests", {})
    return {"questions": max(3, min(int(s.get("questions", 10)), 20)),
            "reteach_below": float(s.get("reteach_below", 50)),
            "praise_from": float(s.get("praise_from", 80))}


# ---------- making a test ----------

GEN_SYSTEM = """You are {teacher}, a teacher in India. Make a test of exactly {n} questions for your student on
what you taught in today's class (below). Use ONLY facts from the class — nothing the class did not cover.
Cover every topic, mix easy and harder questions, no trick questions, nothing unsafe or off-syllabus.
Write the questions in this language and script: {language}.
{fmt}
Return JSON only."""

FORMATS = {
    "mcq": 'Each question has exactly 4 options and exactly one is correct. JSON: {"questions": [{"q": str, '
           '"options": [str, str, str, str], "answer": index 0-3 of the correct option, '
           '"explain": one short line why it is correct, "topic": str}]}',
    "written": 'Short-answer questions (answer in 2-5 lines). JSON: {"questions": [{"q": str, '
               '"answer": a model answer, "points": [2-4 key points a good answer must have], "topic": str}]}',
    "oral": 'Viva questions Sir asks out loud, answered in one or two sentences. JSON: {"questions": [{"q": str, '
            '"answer": a model answer, "points": [1-3 key points], "topic": str}]}',
}


def _clean_questions(mode: str, raw, rng: random.Random) -> list[dict]:
    out = []
    for q in raw if isinstance(raw, list) else []:
        if not isinstance(q, dict):
            continue
        text = str(q.get("q") or "").strip()[:400]
        topic = str(q.get("topic") or "").strip()[:80]
        if not text:
            continue
        if mode == "mcq":
            opts = [str(o).strip()[:200] for o in (q.get("options") or [])]
            ans = q.get("answer")
            if len(opts) != 4 or not all(opts) or len(set(opts)) != 4 or not isinstance(ans, int) or not 0 <= ans <= 3:
                continue
            correct = opts[ans]
            rng.shuffle(opts)  # the model likes putting the right answer first
            out.append({"q": text, "options": opts, "answer": opts.index(correct),
                        "explain": str(q.get("explain") or "").strip()[:300], "topic": topic})
        else:
            model = str(q.get("answer") or "").strip()[:1200]
            points = [str(p).strip()[:200] for p in (q.get("points") or []) if str(p).strip()][:4]
            if not model:
                continue
            out.append({"q": text, "answer": model, "points": points, "topic": topic})
    return out


def create_test(db: Database, llm: LLM, student_id: int, teacher_id: str, teacher_name: str, mode: str,
                session_id: int | None = None, topics: list[str] | None = None, rng: random.Random | None = None,
                now: float | None = None) -> dict:
    if mode not in MODES:
        raise TestError("Choose MCQ, written or oral")
    sid = classroom.latest_session_with_content(db, student_id, session_id)
    if sid is None:
        raise TestError("Study a topic with Sir first — then he can test you on it.")
    material = classroom.class_material(db, student_id, sid, topics)
    if not material:
        raise TestError("Choose at least one topic from the class.")
    n = test_settings(db)["questions"]
    lang = get_language(classroom.main_language(material))
    lines = [f"[Topic: {m['topic']}]\nStudent: {m['question']}\nTeacher: {m['answer']}" for m in material]
    system = GEN_SYSTEM.format(teacher=teacher_name, n=n, language=lang.english_name, fmt=FORMATS[mode])
    try:
        out = llm.chat_json(system, "\n\n".join(lines))
    except Exception:
        raise TestError("Sir couldn't prepare the test right now. Please try again.")
    questions = _clean_questions(mode, out.get("questions"), rng or random.Random())[:n]
    if len(questions) < min(3, n):
        raise TestError("Sir couldn't prepare the test right now. Please try again.")
    used_topics = list(dict.fromkeys(m["topic"] for m in material))
    cur = db.execute("INSERT INTO tests (student_id, teacher_id, session_id, mode, language, topics, questions, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (student_id, teacher_id, sid, mode, lang.code, json.dumps(used_topics, ensure_ascii=False),
                      json.dumps(questions, ensure_ascii=False), now or time.time()))
    return public_view(_load(db, student_id, cur.lastrowid))


def _load(db: Database, student_id: int, test_id: int):
    row = db.one("SELECT * FROM tests WHERE id = ? AND student_id = ?", (test_id, student_id))
    if row is None:
        raise KeyError(test_id)
    return row


def _public_question(mode: str, q: dict) -> dict:
    return {"q": q["q"], **({"options": q["options"]} if mode == "mcq" else {})}


def public_view(row) -> dict:
    """What the app may see: never the correct answer of a question not yet answered."""
    questions = json.loads(row["questions"])
    view = {"id": row["id"], "mode": row["mode"], "language": row["language"], "total": len(questions),
            "index": row["current"], "status": row["status"], "topics": json.loads(row["topics"] or "[]"),
            "question": _public_question(row["mode"], questions[row["current"]]) if row["status"] == "open" else None}
    if row["status"] == "done":
        view["result"] = json.loads(row["outcome"]) if row["outcome"] and row["outcome"].startswith("{") else None
    return view


# ---------- answering ----------

_LETTERS = {"a": 0, "b": 1, "c": 2, "d": 3, "1": 0, "2": 1, "3": 2, "4": 3,
            "ए": 0, "बी": 1, "सी": 2, "डी": 3, "क": 0, "ख": 1, "ग": 2, "घ": 3}


def _mcq_choice(answer, options: list[str]) -> int:
    if isinstance(answer, int) and not isinstance(answer, bool) and 0 <= answer <= 3:
        return answer
    text = str(answer or "").strip()
    low = text.lower()
    for i, o in enumerate(options):
        if low == o.lower():
            return i
    m = re.fullmatch(r"(?:option|opt|विकल्प)?\s*\(?([a-d1-4])\)?\.?", low)
    if m:
        return _LETTERS[m.group(1)]
    if low in _LETTERS:
        return _LETTERS[low]
    raise TestError("Choose one option: A, B, C or D")


GRADE_SYSTEM = """You check one answer in a student's test. Be fair and kind: judge the meaning, not spelling,
grammar or which language/script the student used. Compare with the model answer and key points.
Score 1 = correct, 0.5 = partly correct (some key points), 0 = wrong or no answer.
Write the feedback in this language and script: {language} — one short line, like a caring teacher.
Return JSON only: {{"score": 0 | 0.5 | 1, "feedback": str}}"""


def _grade_text(llm: LLM, q: dict, answer: str, language_name: str) -> tuple[float, str]:
    if not answer.strip():
        return 0.0, ""
    prompt = (f"Question: {q['q']}\nModel answer: {q['answer']}\nKey points: {'; '.join(q['points'])}\n"
              f"Student's answer: {answer}")
    try:
        out = llm.chat_json(GRADE_SYSTEM.format(language=language_name), prompt)
        score = float(out.get("score"))
    except Exception:
        raise TestError("Sir couldn't check this answer right now. Please send it again.")
    score = 1.0 if score >= 0.75 else 0.5 if score >= 0.25 else 0.0
    return score, str(out.get("feedback") or "").strip()[:300]


def answer_question(db: Database, llm: LLM, student_id: int, test_id: int, answer, teacher_name: str,
                    now: float | None = None) -> dict:
    row = _load(db, student_id, test_id)
    if row["status"] != "open":
        raise TestError("This test is already finished.")
    questions = json.loads(row["questions"])
    results = json.loads(row["results"])
    i = row["current"]
    q = questions[i]
    lang = get_language(row["language"])
    if row["mode"] == "mcq":
        choice = _mcq_choice(answer, q["options"])
        score = 1.0 if choice == q["answer"] else 0.0
        given, feedback = q["options"][choice], q.get("explain", "")
        correct_answer = q["options"][q["answer"]]
    else:
        given = str(answer or "").strip()[:2000]
        score, feedback = _grade_text(llm, q, given, lang.english_name)
        correct_answer = q["answer"]
    results.append({"index": i, "given": given, "score": score, "topic": q.get("topic", "")})
    total_score = row["score"] + score
    nxt = i + 1
    done = nxt >= len(questions)
    outcome = json.dumps(_result(db, row, questions, results, total_score, teacher_name), ensure_ascii=False) if done else None
    db.execute("UPDATE tests SET results = ?, current = ?, score = ?, status = ?, outcome = ?, finished_at = ? WHERE id = ?",
               (json.dumps(results, ensure_ascii=False), nxt if not done else i, total_score,
                "done" if done else "open", outcome, (now or time.time()) if done else None, test_id))
    return {"correct": score == 1.0, "score": score, "feedback": feedback, "correct_answer": correct_answer,
            "test": public_view(_load(db, student_id, test_id))}


def _result(db: Database, row, questions: list, results: list, total_score: float, teacher_name: str) -> dict:
    cfg = test_settings(db)
    total = len(questions)
    pct = round(total_score / total * 100) if total else 0
    weak = list(dict.fromkeys(r["topic"] for r in results if r["score"] < 1 and r["topic"]))
    topic_names = weak or json.loads(row["topics"] or "[]")
    outcome = "reteach_offer" if pct < cfg["reteach_below"] else "praise" if pct >= cfg["praise_from"] else "good"
    score_text = f"{total_score:g}/{total}"
    message = t(f"test_{outcome}", row["language"], teacher=teacher_name, score=score_text, pct=pct,
                topics=", ".join(topic_names[:4]))
    return {"outcome": outcome, "score": total_score, "total": total, "percent": pct, "weak_topics": weak,
            "message": message}


def reteach(db: Database, student_id: int, test_id: int, yes: bool) -> str | None:
    """Student's answer to "Shall I teach it again?". Returns the request to send to Sir, or None."""
    row = _load(db, student_id, test_id)
    if row["status"] != "done":
        raise TestError("Finish the test first.")
    result = json.loads(row["outcome"])
    db.execute("UPDATE tests SET reteach = ? WHERE id = ?", ("yes" if yes else "no", test_id))
    if not yes:
        return None
    topics = result.get("weak_topics") or json.loads(row["topics"] or "[]")
    return t("reteach_request", row["language"], topics=", ".join(topics[:4]))


def history(db: Database, student_id: int, limit: int = 20) -> list[dict]:
    rows = db.all("SELECT id, mode, topics, status, outcome, created_at FROM tests WHERE student_id = ? "
                  "ORDER BY id DESC LIMIT ?", (student_id, max(1, min(limit, 100))))
    out = []
    for r in rows:
        res = json.loads(r["outcome"]) if r["outcome"] else None
        out.append({"id": r["id"], "mode": r["mode"], "topics": json.loads(r["topics"] or "[]"),
                    "status": r["status"], "created_at": r["created_at"],
                    "percent": res["percent"] if res else None, "score": res["score"] if res else None,
                    "total": res["total"] if res else None})
    return out
