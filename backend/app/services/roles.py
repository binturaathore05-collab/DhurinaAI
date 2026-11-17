"""B5 · Team roles and what each may do. Checked on the server for every admin request (the panel only hides what a
role can't use). "School Admin" from the brief is the Teacher in our model (teacher dashboard, own students only).
"""

ROLES = {
    "owner": ("Super Admin", "Everything, including the team and money."),
    "safety": ("Safety Admin", "Student conversations, review cases, blocking, safety settings, Emergency."),
    "support": ("Support", "Helps students: accounts, class, parent consent. Can't read conversations or block."),
    "technical": ("Technical", "Teachers, app builds, Emergency, safety tests. No student data."),
    "auditor": ("Auditor", "Read-only: dashboards, audit log, reports, settings. Can't change anything."),
}

_ALL = set(ROLES)
PERMS = {
    "dashboard": _ALL,                                        # safety numbers (no personal data)
    "tests_view": _ALL,
    "teachers_view": {"owner", "technical", "support", "auditor"},
    "teachers_edit": {"owner", "technical"},
    "money": {"owner", "auditor"},                            # reports, payments, exports
    "settings_view": {"owner", "safety", "technical", "auditor"},
    "settings_safety": {"owner", "safety"},                   # AI topics, safety, limits, age groups, students
    "settings_all": {"owner"},                                # company, money split, legal, tests
    "students": {"owner", "safety", "support"},               # student accounts (without their messages)
    "evidence": {"owner", "safety"},                          # conversations, flagged messages, cases, lookups
    "block": {"owner", "safety"},                             # warn / suspend / block / unblock students
    "consent": {"owner", "safety", "support"},                # withdraw a parent's consent on request
    "emergency_view": {"owner", "safety", "technical", "auditor"},
    "emergency": {"owner", "safety", "technical"},
    "tests_run": {"owner", "safety", "technical"},
    "audit": {"owner", "safety", "auditor"},
    "team": {"owner"},
}
SAFETY_SECTIONS = {"ai", "safety", "limits", "age_groups", "students"}


def has(role: str, cap: str) -> bool:
    return role in PERMS.get(cap, set())


def caps(role: str) -> list[str]:
    return sorted(c for c, r in PERMS.items() if role in r)


def label(role: str) -> str:
    return ROLES.get(role, (role, ""))[0]


def catalog() -> list[dict]:
    return [{"key": k, "label": v[0], "text": v[1], "caps": caps(k)} for k, v in ROLES.items()]
