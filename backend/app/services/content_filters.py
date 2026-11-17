"""B9 · Content filters (brief §3): each kind of harmful content is a filter the admin can set in the Safety Center.

Per filter:
  on        on / off. "Off" only stops the filter for students' messages; Sir's own answers are still checked for
            every kind of harm (an AI answer to a child is never let through unchecked).
  level     "age" (follow the student's age group, B2) or strict / medium / relaxed just for this filter
  severity  what a hit counts as on the warnings ladder (A3): "auto" (as the checker decides), "minor" or "serious"
  review    open a case in the Review Center (B4) on every hit (serious hits always do)

Locked filters (sexual, weapons & bombs, drugs, self-harm, breaking the rules) are always on, always serious (self-harm:
always the care reply with the helpline) and always reviewed — a child-safety floor no setting can lower.

Educational questions (biology, reproduction, health, history, science) are never blocked by a stricter filter: the
checker is told so in every level.
"""
from .moderation import Verdict

FILTERS = {
    "sexual": "Sexual, pornographic & adult content",
    "weapons": "Bombs, explosives & weapons",
    "drugs": "Drug & alcohol abuse instructions",
    "self_harm": "Self-harm & suicide",
    "jailbreak": "Trying to make Sir break his rules",
    "violence": "Violence & physical harm",
    "crime": "Criminal instructions (cheating, hacking, stealing)",
    "harassment": "Harassment, bullying & threats",
    "personal_info": "Asking for or giving personal information",
    "dangerous_advice": "Dangerous or misleading advice (medical, stunts, diet)",
}
LOCKED = {"sexual", "weapons", "drugs", "self_harm", "jailbreak"}
LEVELS = ("age", "strict", "medium", "relaxed")
SEVERITIES = ("auto", "minor", "serious")

DEFAULT_FILTERS = {
    **{c: {"on": True, "level": "age", "severity": "serious", "review": True} for c in LOCKED},
    "violence": {"on": True, "level": "age", "severity": "auto", "review": False},
    "crime": {"on": True, "level": "age", "severity": "serious", "review": True},
    "harassment": {"on": True, "level": "age", "severity": "auto", "review": False},
    "personal_info": {"on": True, "level": "age", "severity": "minor", "review": False},
    "dangerous_advice": {"on": True, "level": "age", "severity": "minor", "review": False},
}

# what the safety checker is told when a filter has its own level
LEVEL_TEXT = {
    "strict": "be extra careful — also report mild or borderline cases (at least minor)",
    "medium": "use normal school standards",
    "relaxed": "report only clear, real harm; discussion as a study topic is none",
}


class FilterError(ValueError):
    pass


def _bool(v) -> bool:
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "on", "yes")


def settings_of(admin_settings: dict) -> dict:
    saved = admin_settings.get("filters") or {}
    out = {}
    for c, d in DEFAULT_FILTERS.items():
        s = {**d, **(saved.get(c) or {})} if isinstance(saved.get(c), dict) else dict(d)
        if c in LOCKED:   # the floor: never lowered, whatever was saved
            s.update(on=True, severity="serious", review=True)
        out[c] = s
    return out


def validate(values: dict) -> dict:
    out = {}
    for c, v in (values or {}).items():
        if c not in FILTERS:
            raise FilterError(f"Unknown filter: {c}")
        if not isinstance(v, dict):
            raise FilterError("Each filter needs on/off, level, severity and review")
        d = DEFAULT_FILTERS[c]
        level = v.get("level", d["level"])
        severity = v.get("severity", d["severity"])
        if level not in LEVELS:
            raise FilterError("Filter level must be: as per age group, strict, medium or relaxed")
        if severity not in SEVERITIES:
            raise FilterError("Filter severity must be: as the checker decides, small or serious")
        on, review = _bool(v.get("on", d["on"])), _bool(v.get("review", d["review"]))
        if c in LOCKED and (not on or severity != "serious" or not review):
            raise FilterError(f"“{FILTERS[c]}” protects children and is always on, serious and reviewed")
        out[c] = {"on": on, "level": level, "severity": severity, "review": review}
    return out


def checker_lines(admin_settings: dict) -> str:
    """Extra lines for the safety checker (only for filters with their own level). Part of the cache key."""
    f = settings_of(admin_settings)
    lines = [f"- {c}: {LEVEL_TEXT[s['level']]}." for c, s in f.items() if s["level"] != "age"]
    if not lines:
        return ""
    return ("Per-category settings from the safety team (a real syllabus question is still none):\n"
            + "\n".join(lines))


def apply(v: Verdict, stage: str, admin_settings: dict) -> Verdict:
    """The admin's filter settings applied to the checker's verdict."""
    if v.safe or v.category not in FILTERS or v.category in LOCKED:
        return v
    s = settings_of(admin_settings)[v.category]
    if not s["on"] and stage == "input":
        return Verdict(source=v.source)
    if s["severity"] in ("minor", "serious"):
        return Verdict(v.category, s["severity"], v.source)
    return v


def needs_review(category: str, admin_settings: dict) -> bool:
    f = settings_of(admin_settings)
    return bool(f.get(category, {}).get("review"))


def catalog() -> list[dict]:
    return [{"id": c, "label": label, "locked": c in LOCKED} for c, label in FILTERS.items()]
