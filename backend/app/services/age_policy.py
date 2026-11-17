"""B2 · Safety rules by age group (from the class and "18 or older?" given at signup, B1).

Each group has a strictness and its own extra blocked topics, set by the admin in Settings → "Age groups".
Both the AI teacher's instructions and the independent safety check (A2) use them. In every group a real study
question from the syllabus is answered — strictness changes how sensitive-but-educational topics are handled and
what counts as unsuitable, never whether studies are allowed.
"""
from ..db import Database

GROUPS = {
    "primary": "Class 1–5 (about 6–10 years)",
    "junior": "Class 6–8 (about 11–13 years)",
    "middle": "Class 9–10 (about 14–15 years)",
    "senior": "Class 11–12, under 18 (about 16–17 years)",
    "adult": "18 or older",
}
LEVELS = ("strict", "medium", "relaxed")

DEFAULT_AGE_GROUPS = {
    "primary": {"strictness": "strict", "blocked_topics": ["romance and dating", "horror and gore", "violent games"]},
    "junior": {"strictness": "strict", "blocked_topics": ["romance and dating", "horror and gore"]},
    "middle": {"strictness": "medium", "blocked_topics": ["dating advice"]},
    "senior": {"strictness": "medium", "blocked_topics": []},
    "adult": {"strictness": "relaxed", "blocked_topics": []},
}

# what the AI teacher is told for each strictness
TEACH = {
    "strict": "This is a young student. Keep every explanation simple, gentle and fully child-safe. Sensitive syllabus "
              "topics (puberty, reproduction, health) are fine: explain at the textbook level, briefly and respectfully, "
              "without extra detail. No graphic detail of violence or crime, even in history.",
    "medium": "This is a teenage student. Answer syllabus topics fully at the textbook level, including biology, health "
              "and history, with care and without graphic detail.",
    "relaxed": "This is an adult student (college / competitive exams). Mature educational discussion is fine (health, "
               "law, crime and drugs as subjects of study), but never instructions to cause harm.",
}

# what the safety checker is told for each strictness
CHECK = {
    "strict": "The student is a child (about 6–13). Besides the usual harms, treat as minor: romance or dating talk, "
              "horror or gore, graphic violence, and adult topics that are not in the school syllabus. A school "
              "syllabus question is still none.",
    "medium": "The student is a teenager (about 14–17). Use normal school standards.",
    "relaxed": "The student is an adult. Mature educational discussion (sexual health, drug policy, crime as a law "
               "topic) is none; only real harm, explicit sexual content or instructions to cause harm are unsafe.",
}


class AgePolicyError(Exception):
    pass


def group_of(class_level: str | None, is_adult) -> str | None:
    if is_adult:
        return "adult"
    if not class_level:
        return None
    if class_level == "college":
        return "senior"   # in college but under 18
    try:
        c = int(class_level)
    except ValueError:
        return None
    return "primary" if c <= 5 else "junior" if c <= 8 else "middle" if c <= 10 else "senior"


def settings_of(admin_settings: dict) -> dict:
    saved = admin_settings.get("age_groups") or {}
    out = {}
    for g, d in DEFAULT_AGE_GROUPS.items():
        s = saved.get(g) or {}
        out[g] = {"strictness": s.get("strictness", d["strictness"]),
                  "blocked_topics": list(s.get("blocked_topics", d["blocked_topics"]))}
    return out


def validate(values: dict) -> dict:
    out = {}
    for g, v in (values or {}).items():
        if g not in GROUPS:
            raise AgePolicyError(f"Unknown age group: {g}")
        if not isinstance(v, dict):
            raise AgePolicyError("Each age group needs a strictness and a list of topics")
        level = v.get("strictness", DEFAULT_AGE_GROUPS[g]["strictness"])
        if level not in LEVELS:
            raise AgePolicyError("Strictness must be strict, medium or relaxed")
        topics = v.get("blocked_topics", DEFAULT_AGE_GROUPS[g]["blocked_topics"])
        if isinstance(topics, str):
            topics = [t for t in (x.strip() for x in topics.replace("\n", ",").split(",")) if t]
        topics = [str(t).strip()[:60] for t in topics if str(t).strip()][:30]
        out[g] = {"strictness": level, "blocked_topics": topics}
    return out


def for_student(db: Database, student_id: int | None, admin_settings: dict) -> dict | None:
    """The policy for this student, or None (unknown student: the general rules apply)."""
    if not student_id:
        return None
    r = db.one("SELECT class_level, is_adult FROM students WHERE id = ?", (student_id,))
    if r is None:
        return None
    g = group_of(r["class_level"], r["is_adult"])
    if g is None:
        return None
    return {"group": g, "label": GROUPS[g], **settings_of(admin_settings)[g]}
