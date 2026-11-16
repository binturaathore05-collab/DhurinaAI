"""Teaching Style: how each teacher's AI behaves, set in the teacher dashboard, turned into rules for the model.

See docs/ai-teacher-requirements.md. Everything here is per teacher and can be switched on/off.
"""
import copy
import json

from ..db import Database

PERSONALITIES = {
    "friendly": "Friendly: warm, uses simple words, makes the student feel comfortable.",
    "strict": "Strict: disciplined and precise, expects attention, still respectful, never insulting.",
    "motivational": "Motivational: builds confidence, connects topics to exam success and goals.",
    "professional": "Professional: clear, structured, to the point, like a senior lecturer.",
    "funny": "Funny & interactive: light humour and fun examples, but facts stay exact.",
    "calm": "Calm & patient: slow, reassuring, repeats gently, never rushes the student.",
}

# key -> (title, default on, default text). Teachers can edit the text and switch each one off.
TEACHING = {
    "greeting": ("How I start", True, "Start with a short friendly line and a hook question, in my own words — not the same line every time."),
    "language": ("Language mix", True, "Reply in the student's language. With Hindi speakers, mix common English words naturally (Hinglish)."),
    "story": ("Story-based explanations", True, "Explain a topic as a short story first when it helps (history, events, people)."),
    "real_life": ("Real-life examples", True, "Use everyday examples from the student's life in India."),
    "step_by_step": ("Step-by-step", True, "Break difficult topics and every calculation into small numbered steps."),
    "board": ("Board points", True, "Put 2–5 short key points on the board: names, years, formulas, definitions."),
    "tricks": ("Memory tricks", True, "Give a short trick or mnemonic to remember lists and facts."),
    "exam": ("Exam-oriented points", True, "End important topics with what is most likely to be asked in the exam."),
    "avoid": ("Never does", True, "No politics or personal opinions. Says politely when a question is outside the syllabus."),
}

INTERACTION = {
    "ask_questions": ("Ask questions while teaching", True),
    "wait_for_answer": ("Wait for the student's answer", True),
    "praise": ("Appreciate correct answers", True),
    "correct_politely": ("Correct wrong answers politely", True),
    "motivate": ("Motivate the student", True),
    "use_name": ("Use the student's name (sometimes)", True),
    "adapt_level": ("Adapt to the student's level", True),
    "natural_talk": ("Natural talk: small pauses, self-correction, no robotic or repeated lines", True),
}

# Phase 5 (video avatar + voice). Stored now so the teacher's choices are ready when the avatar launches.
AVATAR = {
    "expressions": ("Facial expressions (smile, thinking, encouraging…)", True),
    "gestures": ("Hand gestures & head movement", True),
    "eye_contact": ("Eye contact & natural blinking", True),
    "look_at_board": ("Look at / point to the board while explaining", True),
    "voice_emotion": ("Emotion in voice, pauses & emphasis", True),
    "lip_sync": ("Accurate lip-sync", True),
    "continuity": ("Same face, clothes & background every time", True),
}

EMOTIONS = ["smile", "encouraging", "thinking", "serious", "excited", "calm", "surprised"]
LEVELS = ["beginner", "intermediate", "advanced"]


MAX_PERSONALITIES = 3


def default_style() -> dict:
    return {
        "personalities": ["friendly"],     # 1–3, first = strongest
        "teaching": {k: {"title": t, "on": on, "text": txt} for k, (t, on, txt) in TEACHING.items()},
        "interaction": {k: on for k, (_, on) in INTERACTION.items()},
        "avatar": {k: on for k, (_, on) in AVATAR.items()},
    }


def get_style(db: Database, teacher_id: str) -> dict:
    row = db.one("SELECT style FROM teachers WHERE id = ?", (teacher_id,))
    style = default_style()
    saved = json.loads(row["style"]) if row and row["style"] else {}
    style["personalities"] = _clean_personalities(saved) or style["personalities"]
    for key, item in (saved.get("teaching") or {}).items():
        if key in style["teaching"] and isinstance(item, dict):
            style["teaching"][key]["on"] = bool(item.get("on", True))
            if str(item.get("text", "")).strip():
                style["teaching"][key]["text"] = str(item["text"]).strip()[:600]
    for group in ("interaction", "avatar"):
        for key, on in (saved.get(group) or {}).items():
            if key in style[group]:
                style[group][key] = bool(on)
    return style


def _clean_personalities(data: dict) -> list[str]:
    """Accepts the list form, or the older personality / personality_2 form."""
    raw = data.get("personalities")
    if not isinstance(raw, list):
        raw = [data.get("personality"), data.get("personality_2")]
    out = []
    for p in raw:
        if p in PERSONALITIES and p not in out:
            out.append(p)
    return out[:MAX_PERSONALITIES]


def save_style(db: Database, teacher_id: str, data: dict) -> dict:
    merged = get_style(db, teacher_id)
    incoming = copy.deepcopy(data or {})
    chosen = _clean_personalities(incoming)
    if chosen:
        merged["personalities"] = chosen
    for key, item in (incoming.get("teaching") or {}).items():
        if key in merged["teaching"] and isinstance(item, dict):
            if "on" in item:
                merged["teaching"][key]["on"] = bool(item["on"])
            if str(item.get("text", "")).strip():
                merged["teaching"][key]["text"] = str(item["text"]).strip()[:600]
    for group in ("interaction", "avatar"):
        for key, on in (incoming.get(group) or {}).items():
            if key in merged[group]:
                merged[group][key] = bool(on)
    db.execute("UPDATE teachers SET style = ? WHERE id = ?", (json.dumps(merged, ensure_ascii=False), teacher_id))
    return merged


def style_rules(style: dict, student_name: str | None, level: str) -> str:
    """The part of the system prompt that makes the model teach like THIS teacher, for THIS student."""
    s = style
    ps = s["personalities"]
    lines = [f"Personality: {PERSONALITIES[ps[0]]}"]
    if len(ps) > 1:
        lines.append("Blend in naturally, a little less strongly:")
        lines += [f"- {PERSONALITIES[p]}" for p in ps[1:]]
        lines.append("Choose the side that fits the moment (e.g. patient after a mistake, funny when the student is relaxed).")
    lines.append("How you teach:")
    lines += [f"- {v['title']}: {v['text']}" for v in s["teaching"].values() if v["on"]]
    it = s["interaction"]
    talk = []
    if it.get("ask_questions"):
        talk.append("End with ONE short question that checks understanding (the follow_up).")
    if it.get("wait_for_answer"):
        talk.append("Do not answer your own follow_up question; wait for the student.")
    if it.get("praise"):
        talk.append("When the student answers your question correctly, praise them warmly and specifically.")
    if it.get("correct_politely"):
        talk.append("When they answer wrongly, correct them gently: say what was right, then the correct answer.")
    if it.get("motivate"):
        talk.append("Encourage the student, especially after mistakes.")
    if it.get("use_name") and student_name:
        talk.append(f"The student's name is {student_name}. Use it naturally now and then, not in every reply.")
    if it.get("natural_talk"):
        talk.append("Sound like a real person talking: short sentences, natural pauses (…), occasional "
                    "self-correction. Never reuse the same opening or praise line as in the recent conversation.")
    if it.get("adapt_level"):
        talk.append({
            "beginner": "This student is a BEGINNER: very simple words, one idea at a time, more examples, go slowly.",
            "intermediate": "This student is INTERMEDIATE: normal depth, connect to related topics.",
            "advanced": "This student is ADVANCED: be concise, add depth, exam-level detail and tricky points.",
        }[level])
    if talk:
        lines.append("Talking with the student:")
        lines += [f"- {x}" for x in talk]
    return "\n".join(lines)


# ---------- per-student level (adapts from answers to follow-up questions) ----------

def get_level(db: Database, student_id: int) -> str:
    row = db.one("SELECT level FROM students WHERE id = ?", (student_id,))
    return row["level"] if row and row["level"] in LEVELS else "intermediate"


def record_check(db: Database, student_id: int, correct: bool) -> str:
    """Move the level after the student answers the teacher's question: 3 right in a row → up, 2 wrong → down."""
    row = db.one("SELECT level, streak FROM students WHERE id = ?", (student_id,))
    level = row["level"] if row["level"] in LEVELS else "intermediate"
    streak = row["streak"] or 0
    streak = (streak + 1 if streak >= 0 else 1) if correct else (streak - 1 if streak <= 0 else -1)
    i = LEVELS.index(level)
    if streak >= 3 and i < 2:
        level, streak = LEVELS[i + 1], 0
    elif streak <= -2 and i > 0:
        level, streak = LEVELS[i - 1], 0
    db.execute("UPDATE students SET level = ?, streak = ? WHERE id = ?", (level, streak, student_id))
    return level
