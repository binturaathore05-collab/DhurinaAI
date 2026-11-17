"""Class sessions and whole-class notes.

A class session runs from the first question until the student taps "End class" (or 30 minutes pass with no
question). Notes are made from the whole class: greetings, small talk and off-topic redirects are left out, the
rest is grouped by topic, and the student can untick topics they don't want. One class = one PDF; saving again
during the same class updates that PDF instead of making a new one.
"""
import json
import os
import time
from collections import Counter

from ..db import Database
from .llm import LLM
from . import notes_pdf

IDLE_SECONDS = 30 * 60


class ClassError(ValueError):
    pass


# ---------- sessions ----------

def current_session(db: Database, student_id: int, teacher_id: str, now: float | None = None) -> int:
    """The class in progress, or a new one if the last class ended or went idle."""
    now = now or time.time()
    row = db.one("SELECT id, last_at FROM class_sessions WHERE student_id = ? AND ended_at IS NULL "
                 "ORDER BY id DESC LIMIT 1", (student_id,))
    if row and now - row["last_at"] < IDLE_SECONDS:
        db.execute("UPDATE class_sessions SET last_at = ? WHERE id = ?", (now, row["id"]))
        return row["id"]
    if row:  # idle too long: close it
        db.execute("UPDATE class_sessions SET ended_at = last_at WHERE id = ?", (row["id"],))
    cur = db.execute("INSERT INTO class_sessions (student_id, teacher_id, started_at, last_at) VALUES (?, ?, ?, ?)",
                     (student_id, teacher_id, now, now))
    return cur.lastrowid


def open_session(db: Database, student_id: int, now: float | None = None) -> int | None:
    """The class in progress without starting a new one (None if there is none)."""
    now = now or time.time()
    row = db.one("SELECT id, last_at FROM class_sessions WHERE student_id = ? AND ended_at IS NULL "
                 "ORDER BY id DESC LIMIT 1", (student_id,))
    return row["id"] if row and now - row["last_at"] < IDLE_SECONDS else None


def end_session(db: Database, student_id: int, now: float | None = None) -> int | None:
    sid = open_session(db, student_id, now)
    if sid:
        db.execute("UPDATE class_sessions SET ended_at = ? WHERE id = ?", (now or time.time(), sid))
    return sid


def _study_rows(db: Database, student_id: int, session_id: int) -> list:
    """Everything worth keeping from one class: no redirects, no greetings/small talk, no empty answers."""
    rows = db.all("SELECT id, question, answer, topic, language, sources FROM qa_history "
                  "WHERE student_id = ? AND session_id = ? AND origin != 'redirect' "
                  "AND COALESCE(notes_worthy, 1) = 1 AND TRIM(answer) != '' ORDER BY id", (student_id, session_id))
    return list(rows)


def latest_session_with_content(db: Database, student_id: int, prefer: int | None = None) -> int | None:
    """The given class if it taught something, else the most recent class that did."""
    if prefer and _study_rows(db, student_id, prefer):
        return prefer
    for r in db.all("SELECT id FROM class_sessions WHERE student_id = ? ORDER BY id DESC LIMIT 20", (student_id,)):
        if _study_rows(db, student_id, r["id"]):
            return r["id"]
    return None


def _topic_key(row) -> str:
    return (row["topic"] or "").strip() or row["question"].strip()[:60]


def session_topics(db: Database, student_id: int, session_id: int) -> list[dict]:
    """Topics taught in a class, in the order they came up, for the 'choose topics' list."""
    groups: dict[str, dict] = {}
    for r in _study_rows(db, student_id, session_id):
        key = _topic_key(r)
        g = groups.setdefault(key.lower(), {"topic": key, "questions": 0})
        g["questions"] += 1
    return list(groups.values())


def class_material(db: Database, student_id: int, session_id: int, topics: list[str] | None = None) -> list[dict]:
    """The Q&As of a class, optionally only the chosen topics."""
    wanted = {x.strip().lower() for x in topics or [] if str(x).strip()}
    out = []
    for r in _study_rows(db, student_id, session_id):
        key = _topic_key(r)
        if wanted and key.lower() not in wanted:
            continue
        out.append({"id": r["id"], "topic": key, "question": r["question"], "answer": r["answer"],
                    "language": r["language"]})
    return out


def main_language(material: list[dict]) -> str:
    return Counter(m["language"] for m in material).most_common(1)[0][0] if material else "en"


# ---------- class notes ----------

NOTES_SYSTEM = """You turn one class between a teacher and a student into clean study notes.
Use ONLY the facts in the teacher's answers given below. Do not add new facts, do not change names, dates or numbers.
Leave out greetings, small talk, praise and questions the teacher asked the student.
Group by topic: one section per topic, a clear heading, 2-8 short points, and a 1-2 line summary at the end of each section if useful.
Write in this language and script: {language}.
Return JSON only: {{"title": str, "sections": [{{"heading": str, "points": [str], "summary": str}}]}}"""


def _fallback_sections(material: list[dict]) -> list[dict]:
    """If the AI is unavailable, notes are still made: one section per topic, the teacher's own answers."""
    sections: dict[str, dict] = {}
    for m in material:
        s = sections.setdefault(m["topic"].lower(), {"heading": m["topic"], "points": [], "summary": ""})
        s["points"] += [p.strip() for p in m["answer"].split("\n") if p.strip()]
    return list(sections.values())


def compose_notes(llm: LLM, material: list[dict], language_name: str) -> dict:
    if not material:
        raise ClassError("Nothing to save yet — ask Sir something about your studies first.")
    lines = []
    for m in material:
        lines.append(f"[Topic: {m['topic']}]\nStudent: {m['question']}\nTeacher: {m['answer']}")
    try:
        out = llm.chat_json(NOTES_SYSTEM.format(language=language_name), "\n\n".join(lines))
        sections = []
        for s in out.get("sections") or []:
            heading = str(s.get("heading") or "").strip()[:120]
            points = [str(p).strip()[:600] for p in (s.get("points") or []) if str(p).strip()][:12]
            if heading and points:
                sections.append({"heading": heading, "points": points,
                                 "summary": str(s.get("summary") or "").strip()[:400]})
        if not sections:
            raise ValueError("empty notes")
        title = str(out.get("title") or "").strip()[:120] or sections[0]["heading"]
    except Exception:
        sections = _fallback_sections(material)
        title = " · ".join(s["heading"] for s in sections[:3])[:120]
    return {"title": title, "sections": sections}


def save_class_notes(db: Database, llm: LLM, student_id: int, teacher_name: str, notes_dir: str,
                     session_id: int | None, topics: list[str] | None = None, renderer=None) -> dict:
    """Make (or update) the PDF notes for one class. Returns the saved_notes row."""
    from ..languages import get_language
    session_id = latest_session_with_content(db, student_id, session_id)
    if session_id is None:
        raise ClassError("Nothing to save yet — ask Sir something about your studies first.")
    material = class_material(db, student_id, session_id, topics)
    if not material:
        raise ClassError("Choose at least one topic from the class.")
    used_topics = list(dict.fromkeys(m["topic"] for m in material))
    upto = max(m["id"] for m in material)
    existing = db.one("SELECT id, topics, qa_upto FROM saved_notes WHERE student_id = ? AND kind = 'class' "
                      "AND session_id = ?", (student_id, session_id))
    if existing and existing["qa_upto"] == upto and json.loads(existing["topics"] or "[]") == used_topics:
        # nothing new since the last save: same PDF, no AI call
        row = dict(db.one("SELECT id, qa_id, title, created_at, kind, session_id, topics FROM saved_notes "
                          "WHERE id = ?", (existing["id"],)))
        row["topics"], row["updated"], row["unchanged"] = used_topics, False, True
        return row
    lang = get_language(main_language(material))
    notes = compose_notes(llm, material, lang.english_name)
    started = db.one("SELECT started_at FROM class_sessions WHERE id = ?", (session_id,))
    date_text = time.strftime("%d %b %Y", time.localtime(started["started_at"] if started else time.time()))
    html_text = notes_pdf.build_class_notes_html(teacher_name, notes["title"], notes["sections"], lang.code, date_text)
    version = int(time.time() * 1000)
    path = os.path.join(notes_dir, str(student_id), f"class_{session_id}_{version}.pdf")
    (renderer or notes_pdf.render_pdf)(html_text, path)
    if existing:
        old = db.one("SELECT pdf_path FROM saved_notes WHERE id = ?", (existing["id"],))["pdf_path"]
        db.execute("UPDATE saved_notes SET title = ?, pdf_path = ?, topics = ?, qa_upto = ?, "
                   "created_at = CURRENT_TIMESTAMP WHERE id = ?",
                   (notes["title"], path, json.dumps(used_topics, ensure_ascii=False), upto, existing["id"]))
        if old != path and os.path.exists(old):
            os.remove(old)
        note_id = existing["id"]
    else:
        cur = db.execute("INSERT INTO saved_notes (student_id, qa_id, title, pdf_path, kind, session_id, topics, qa_upto) "
                         "VALUES (?, NULL, ?, ?, 'class', ?, ?, ?)",
                         (student_id, notes["title"], path, session_id, json.dumps(used_topics, ensure_ascii=False), upto))
        note_id = cur.lastrowid
    row = dict(db.one("SELECT id, qa_id, title, created_at, kind, session_id, topics FROM saved_notes WHERE id = ?",
                      (note_id,)))
    row["topics"] = json.loads(row["topics"] or "[]")
    row["updated"] = bool(existing)
    return row


def class_summary(db: Database, student_id: int, session_id: int | None) -> dict:
    """What the app shows for the class in progress: its topics and whether a test can be offered."""
    sid = session_id if session_id and _study_rows(db, student_id, session_id) else None
    topics = session_topics(db, student_id, sid) if sid else []
    saved = db.one("SELECT id FROM saved_notes WHERE student_id = ? AND kind = 'class' AND session_id = ?",
                   (student_id, sid)) if sid else None
    return {"session_id": sid, "topics": topics, "notes_id": saved["id"] if saved else None,
            "can_test": bool(topics)}
