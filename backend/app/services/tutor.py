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


def _system_prompt(teacher: TeacherProfile, language_name: str) -> str:
    return f"""You are the AI avatar of {teacher.name}, a teacher{f' of {teacher.subject}' if teacher.subject else ''} in India.
Speak like {teacher.name} talking to one student on a video call: warm, clear, simple sentences, short enough to say aloud.
Reply in exactly the same language and script the student used (it looks like {language_name}).
If they wrote Hindi in Roman letters (Hinglish), reply in Hinglish. Keep names and dates accurate.
Rules:
- Only help with studies. Politely decline anything unrelated to learning.
- Never invent facts. If you are not sure, say so honestly.
- For maths or calculations, work step by step and double-check the result.
- End with ONE short question to check the student understood (the "follow_up").
Return JSON: {{"answer": str, "follow_up": str, "found_in_notes": bool, "used_sources": [int],
"language": the BCP-47 code of the language you replied in, e.g. "hi", "pa", "en", "hi-Latn"}}"""


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
        system = _system_prompt(teacher, lang.english_name)

        verified = self.kb.find_verified(teacher.id, question)
        hits = [] if verified else self.kb.search(teacher.id, self._search_queries(question))

        origin, sources, reply = "general_ai", [], None
        if verified or hits:
            reply = self.llm.chat_json(system, _notes_prompt(question, hits, verified["answer"] if verified else None))
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
            reply = self.llm.chat_json(system, f"Student's question: {question}\n"
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
        cur = self.db.execute(
            "INSERT INTO qa_history (student_id, question, answer, follow_up, origin, sources, language, needs_review) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (student_id, question, reply.get("answer", ""), reply.get("follow_up", ""), origin,
             json.dumps(sources, ensure_ascii=False), lang.code, int(needs_review)))
        return TutorAnswer(cur.lastrowid, reply.get("answer", ""), reply.get("follow_up", ""), origin, sources,
                           lang.code, needs_review)


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
