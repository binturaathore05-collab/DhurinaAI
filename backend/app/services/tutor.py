"""The AI teacher: answers a student's question in the student's language, in the teacher's style.

Order of trust:
  1. verified   – an answer the teacher approved earlier
  2. teacher_notes – grounded in the teacher's own notes (sources shown to the student)
  3. general_ai – general AI knowledge; flagged and queued for the teacher to review
Every answer is saved to the student's history (My Library).
"""
import json
from dataclasses import dataclass, field

from ..db import Database
from ..i18n import t
from ..languages import LANGUAGES, detect_language, get_language
from . import style as style_mod
from .knowledge import Hit, KnowledgeBase
from .llm import LLM

SAVE_PHRASES = [
    "save this", "save notes", "save as notes", "save it",
    "सेव कर", "सेव करो", "नोट्स सेव", "नोट सेव", "सहेज",
    "ਸੇਵ ਕਰ", "ਨੋਟਸ ਸੇਵ",
]


def is_save_command(text: str) -> bool:
    """True when the student asks (by voice or text) to save the last answer as notes."""
    low = text.lower()
    return any(p in low for p in SAVE_PHRASES)


@dataclass
class TeacherProfile:
    id: str
    name: str
    subject: str = ""


@dataclass
class TutorAnswer:
    qa_id: int
    answer: str
    follow_up: str
    origin: str
    sources: list[dict] = field(default_factory=list)
    language: str = "hi"
    needs_review: bool = False
    emotion: str = "smile"            # drives the avatar's face and voice tone (Phase 5)
    emphasis: list[str] = field(default_factory=list)   # words to stress when speaking
    board: list[str] = field(default_factory=list)      # short points shown on the board
    level: str = "intermediate"       # the student's current level
    check: str | None = None          # "correct" / "wrong" when the student answered Sir's question


def _system_prompt(teacher: TeacherProfile, language_name: str, rules: str) -> str:
    return f"""You are the AI avatar of {teacher.name}, a teacher{f' of {teacher.subject}' if teacher.subject else ''} in India.
You are on a live video call with ONE student. Teach like a real human teacher, never like a robot.
Reply in exactly the same language and script the student used (it looks like {language_name}).
If they wrote Hindi in Roman letters (Hinglish), reply in Hinglish. Keep names, dates and numbers accurate.
Only help with studies. Never invent facts; if you are not sure, say so honestly.

{rules}

Return JSON only:
{{"answer": str, "follow_up": str,
"answered_follow_up": bool (true if this message is the student's answer to your previous question),
"follow_up_correct": bool or null (was that answer correct?),
"found_in_notes": bool, "used_sources": [int],
"emotion": one of {style_mod.EMOTIONS} (your face/voice for this reply),
"emphasis": [up to 4 important words to stress when speaking],
"board": [2-5 very short key points to write on the board, or [] for small talk],
"language": BCP-47 code of the language you replied in, e.g. "hi", "pa", "en", "hi-Latn"}}"""


def _history_block(recent: list) -> str:
    if not recent:
        return ""
    parts = ["Recent conversation (oldest first) — continue naturally, don't repeat yourself:"]
    for r in recent:
        parts.append(f"Student: {r['question']}\nYou: {r['answer']}" + (f"\nYou asked: {r['follow_up']}" if r["follow_up"] else ""))
    return "\n".join(parts) + "\n\n"


def _notes_prompt(question: str, hits: list[Hit], verified: str | None) -> str:
    parts = [f"Student's question: {question}", ""]
    if verified:
        parts += ["The teacher has approved this answer. Explain it, do not change the facts:", verified, ""]
    if hits:
        parts.append("Use ONLY these extracts from the teacher's own notes. Set found_in_notes=false if they do "
                     "not answer the question. List the numbers of the extracts you used in used_sources.")
        for i, h in enumerate(hits, 1):
            parts.append(f"[{i}] ({h.source_title}) {h.text}")
    return "\n".join(parts)


class Tutor:
    def __init__(self, db: Database, kb: KnowledgeBase, llm: LLM):
        self.db, self.kb, self.llm = db, kb, llm

    def _search_queries(self, question: str) -> list[str]:
        """The question itself plus an English keyword version, so Hindi/Punjabi questions match English notes."""
        try:
            out = self.llm.chat_json(
                "Rewrite the student's question as short English search keywords. Return JSON {\"query\": str}.",
                question)
            q = str(out.get("query", "")).strip()
            return [question, q] if q else [question]
        except Exception:
            return [question]

    def answer(self, student_id: int, teacher: TeacherProfile, question: str) -> TutorAnswer:
        lang = get_language(detect_language(question))
        st = self.db.one("SELECT name FROM students WHERE id = ?", (student_id,))
        level = style_mod.get_level(self.db, student_id)
        rules = style_mod.style_rules(style_mod.get_style(self.db, teacher.id), st["name"] if st else None, level)
        system = _system_prompt(teacher, lang.english_name, rules)
        recent = list(reversed(self.db.all("SELECT question, answer, follow_up FROM qa_history WHERE student_id = ? "
                                           "ORDER BY id DESC LIMIT 3", (student_id,))))
        context = _history_block(recent)

        verified = self.kb.find_verified(teacher.id, question)
        hits = [] if verified else self.kb.search(teacher.id, self._search_queries(question))

        origin, sources, reply = "general_ai", [], None
        if verified or hits:
            reply = self.llm.chat_json(system, context + _notes_prompt(question, hits, verified["answer"] if verified else None))
            if verified:
                origin = "verified"
                sources = [{"title": t("source_teacher_notes", lang.code), "ref": "verified"}]
            elif reply.get("found_in_notes"):
                origin = "teacher_notes"
                used = [i for i in reply.get("used_sources", []) if isinstance(i, int) and 1 <= i <= len(hits)] or [1]
                sources = [{"title": hits[i - 1].source_title, "ref": hits[i - 1].source_ref} for i in used]
            else:
                reply = None  # notes did not cover it: fall through to general knowledge
        if reply is None:
            reply = self.llm.chat_json(system, context + f"Student's question: {question}\n"
                                               "This is not in the teacher's notes; answer from general knowledge.")
            sources = [{"title": t("source_general_ai", lang.code), "ref": None}]

        reported = str(reply.get("language", "")).strip()
        if reported in LANGUAGES:  # trust the model when it names a language we know (e.g. Marathi vs Hindi)
            lang = LANGUAGES[reported]
            if origin == "general_ai":
                sources = [{"title": t("source_general_ai", lang.code), "ref": None}]
            elif origin == "verified":
                sources = [{"title": t("source_teacher_notes", lang.code), "ref": "verified"}]
        needs_review = origin == "general_ai"
        # did the student just answer Sir's question? → adapt the level
        check = None
        if recent and recent[-1]["follow_up"] and reply.get("answered_follow_up") \
                and isinstance(reply.get("follow_up_correct"), bool):
            check = "correct" if reply["follow_up_correct"] else "wrong"
            level = style_mod.record_check(self.db, student_id, reply["follow_up_correct"])
            needs_review = False  # a reply to Sir's own question, not a new fact to review
        emotion = reply.get("emotion") if reply.get("emotion") in style_mod.EMOTIONS else (
            "encouraging" if check == "wrong" else "smile")
        board = [str(b)[:80] for b in (reply.get("board") or []) if str(b).strip()][:5]
        emphasis = [str(w)[:40] for w in (reply.get("emphasis") or []) if str(w).strip()][:4]
        cur = self.db.execute(
            "INSERT INTO qa_history (student_id, question, answer, follow_up, origin, sources, language, needs_review, "
            "emotion, board, emphasis, check_result) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (student_id, question, reply.get("answer", ""), reply.get("follow_up", ""), origin,
             json.dumps(sources, ensure_ascii=False), lang.code, int(needs_review), emotion,
             json.dumps(board, ensure_ascii=False), json.dumps(emphasis, ensure_ascii=False), check))
        return TutorAnswer(cur.lastrowid, reply.get("answer", ""), reply.get("follow_up", ""), origin, sources,
                           lang.code, needs_review, emotion, emphasis, board, level, check)


# ---------- teacher review queue ----------

def review_queue(db: Database, teacher_id: str) -> list[dict]:
    rows = db.all("SELECT q.* FROM qa_history q JOIN students s ON s.id = q.student_id "
                  "WHERE s.teacher_id = ? AND q.needs_review = 1 ORDER BY q.id DESC", (teacher_id,))
    return [dict(r) for r in rows]


def approve_answer(db: Database, teacher_id: str, qa_id: int, corrected_answer: str | None = None) -> None:
    """Teacher approves (optionally corrects) an answer; it becomes a verified answer for future students."""
    row = db.one("SELECT q.* FROM qa_history q JOIN students s ON s.id = q.student_id "
                 "WHERE q.id = ? AND s.teacher_id = ?", (qa_id, teacher_id))
    if row is None:
        raise KeyError(qa_id)
    answer = corrected_answer or row["answer"]
    db.execute("INSERT INTO verified_answers (teacher_id, question, answer, language) VALUES (?, ?, ?, ?)",
               (teacher_id, row["question"], answer, row["language"]))
    db.execute("UPDATE qa_history SET needs_review = 0 WHERE id = ?", (qa_id,))
