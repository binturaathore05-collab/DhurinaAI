"""A4 · Emergency kill switches. One click in admin → Emergency stops a part of the AI for everyone, at once,
checked on the server for every request. Turning back on needs a note that it was checked. Every change is logged.

Switches (key → what stops while it is off):
  all_ai            AI chat for every teacher (questions, class notes, tests). Notes, library, payments keep working.
  teacher:<id>      the AI of one teacher's app
  model:<name>      one AI model; jobs move to the next model in line (main → backup), or AI chat pauses if none
  voice / photo     voice and photo questions (switch ready now, used when those features ship)
"""
import time

from ..db import Database

FEATURES = {
    "all_ai": "AI chat for all teachers",
    "voice": "Voice chat",
    "photo": "Photo questions",
}


class AIPaused(Exception):
    """The AI is switched off (all, this teacher, or no model left)."""


def off_keys(db: Database) -> dict:
    return {r["key"]: dict(r) for r in db.all("SELECT * FROM kill_switches WHERE off = 1")}


def is_off(db: Database, key: str) -> bool:
    return db.one("SELECT 1 FROM kill_switches WHERE key = ? AND off = 1", (key,)) is not None


def set_switch(db: Database, key: str, off: bool, reason: str, by: str, now: float | None = None) -> None:
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Write what happened" if off else "Write what was checked before turning it back on")
    if not (key in FEATURES or key.startswith("teacher:") or key.startswith("model:")):
        raise ValueError("Unknown switch")
    if key.startswith("teacher:") and not db.one("SELECT 1 FROM teachers WHERE id = ?", (key[8:],)):
        raise ValueError("Unknown teacher")
    now = now or time.time()
    if is_off(db, key) == off:
        raise ValueError("It is already " + ("off" if off else "on"))
    db.execute("INSERT INTO kill_switches (key, off, reason, by_who, at) VALUES (?, ?, ?, ?, ?) "
               "ON CONFLICT(key) DO UPDATE SET off = excluded.off, reason = excluded.reason, by_who = excluded.by_who, "
               "at = excluded.at", (key, int(off), reason[:500], by, now))
    db.execute("INSERT INTO kill_switch_log (key, off, reason, by_who, at) VALUES (?, ?, ?, ?, ?)",
               (key, int(off), reason[:500], by, now))


def ai_paused_for(db: Database, teacher_id: str | None) -> bool:
    off = off_keys(db)
    return "all_ai" in off or (teacher_id is not None and f"teacher:{teacher_id}" in off)


class ModelRouter:
    """Calls the first AI model in line that is not switched off. Raises AIPaused when none is left."""

    def __init__(self, db: Database, models: list[tuple[str, object]], track: bool = False):
        self.db, self.track = db, track
        self.models = [(name, client) for name, client in models if client is not None]

    def pick(self):
        off = off_keys(self.db)
        for name, client in self.models:
            if not name or f"model:{name}" not in off:
                if self.track:   # A5: remember which model wrote this reply
                    from .audit import used_model
                    used_model.set(name or "dev-fake")
                return client
        raise AIPaused("no AI model available")

    def available(self) -> bool:
        try:
            self.pick()
            return True
        except AIPaused:
            return False

    def chat_json(self, system: str, user: str) -> dict:
        return self.pick().chat_json(system, user)

    def __getattr__(self, name):   # FakeLLM.replies / .calls in tests
        return getattr(self.models[0][1], name)

    def __setattr__(self, name, value):
        if name in ("db", "models", "track"):
            object.__setattr__(self, name, value)
        else:
            setattr(self.models[0][1], name, value)


def overview(db: Database, models: list[dict]) -> dict:
    off = off_keys(db)
    teachers = [{"id": r["id"], "name": r["name"], "off": f"teacher:{r['id']}" in off,
                 "since": off.get(f"teacher:{r['id']}", {}).get("at"),
                 "reason": off.get(f"teacher:{r['id']}", {}).get("reason")}
                for r in db.all("SELECT id, name FROM teachers ORDER BY name")]
    feats = [{"key": k, "label": v, "off": k in off, "since": off.get(k, {}).get("at"),
              "reason": off.get(k, {}).get("reason"), "by": off.get(k, {}).get("by_who")} for k, v in FEATURES.items()]
    for m in models:
        key = f"model:{m['name']}"
        m.update(key=key, off=key in off, since=off.get(key, {}).get("at"), reason=off.get(key, {}).get("reason"))
    log = [dict(r) for r in db.all("SELECT * FROM kill_switch_log ORDER BY at DESC, id DESC LIMIT 50")]
    names = {r["id"]: r["name"] for r in db.all("SELECT id, name FROM teachers")}
    for row in log:
        k = row["key"]
        row["label"] = (FEATURES.get(k) or (f"AI of {names.get(k[8:], k[8:])}" if k.startswith("teacher:")
                                             else f"AI model {k[6:]}" if k.startswith("model:") else k))
    return {"features": feats, "teachers": teachers, "models": models, "log": log, "any_off": bool(off)}
