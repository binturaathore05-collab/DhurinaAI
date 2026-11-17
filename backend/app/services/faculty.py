"""Multi-teacher: the faculty (AI teachers) inside one institute, and which one answers the student.

One row in `teachers` is still one institute = one white-label app (branding, students, plans, payment, split).
Inside it, `faculty` lists the AI teachers: name, photo, subjects, keywords, teaching instructions, voice.
A solo teacher is an institute with one faculty, created automatically, so existing apps keep working unchanged.

Routing costs no extra AI call:
  1. The student asks for a teacher ("Maths wale sir ko bulao", any language) → that teacher.
  2. The input safety check (one small-model call that runs anyway) also returns the question's subject;
     if that is off, a free keyword match on the subject list is used instead.
  3. Sticky: Sir stays the same unless the question clearly belongs to another teacher's subject.
     "ok", "aur batao", a reply to Sir's question never switch.
"""
import json
import re
import time
from dataclasses import dataclass

from ..db import Database

# subject key → (label, keywords). Keywords: English, Hinglish, Hindi, Punjabi. Whole words / phrases only.
SUBJECTS: dict[str, tuple[str, list[str]]] = {
    "history": ("History", ["history", "itihas", "इतिहास", "ਇਤਿਹਾਸ", "mughal", "मुगल", "akbar", "अकबर", "battle", "yudh",
                            "युद्ध", "haldighati", "हल्दीघाटी", "rana pratap", "राणा प्रताप", "maharana", "महाराणा",
                            "freedom struggle", "स्वतंत्रता संग्राम", "harappa", "हड़प्पा", "maurya", "मौर्य", "gupta",
                            "rajput", "राजपूत", "british", "ancient", "medieval", "मध्यकालीन", "प्राचीन", "dynasty",
                            "वंश", "1857", "gandhi", "गांधी", "रियासत", "riyasat"]),
    "geography": ("Geography", ["geography", "bhugol", "भूगोल", "ਭੂਗੋਲ", "river", "nadi", "नदी", "mountain", "parvat",
                                "पर्वत", "climate", "jalvayu", "जलवायु", "soil", "mitti", "मिट्टी", "desert", "मरुस्थल",
                                "thar", "थार", "latitude", "longitude", "plateau", "पठार", "map", "naksha", "monsoon",
                                "मानसून", "aravalli", "अरावली"]),
    "polity": ("Polity / Civics", ["polity", "civics", "constitution", "samvidhan", "संविधान", "parliament", "sansad",
                                   "संसद", "article", "anuchhed", "अनुच्छेद", "fundamental rights", "मौलिक अधिकार",
                                   "governor", "rajyapal", "राज्यपाल", "panchayat", "पंचायत", "lok sabha", "लोकसभा",
                                   "rajya sabha", "राज्यसभा", "supreme court", "high court", "election commission"]),
    "economics": ("Economics", ["economics", "arthshastra", "अर्थशास्त्र", "gdp", "inflation", "mudrasphiti", "मुद्रास्फीति",
                                "budget", "बजट", "bank", "rbi", "tax", "kar", "demand", "supply", "market"]),
    "maths": ("Mathematics", ["math", "maths", "mathematics", "ganit", "गणित", "ਗਣਿਤ", "algebra", "बीजगणित", "geometry",
                              "ज्यामिति", "trigonometry", "त्रिकोणमिति", "equation", "samikaran", "समीकरण", "fraction", "percent",
                              "bhinn", "भिन्न", "percentage", "pratishat", "प्रतिशत", "profit", "loss", "labh", "hani",
                              "लाभ", "हानि", "ratio", "anupat", "अनुपात", "average", "ausat", "औसत", "simple interest",
                              "compound interest", "byaj", "ब्याज", "lcm", "hcf", "lasa", "masa", "लघुत्तम", "महत्तम",
                              "triangle", "tribhuj", "त्रिभुज", "area", "kshetrafal", "क्षेत्रफल", "square root",
                              "vargmool", "वर्गमूल", "number system", "sankhya", "संख्या", "solve", "हल करो", "hal karo",
                              "calculate", "time and work", "speed", "chal", "probability", "प्रायिकता"]),
    "reasoning": ("Reasoning", ["reasoning", "tark", "तर्कशक्ति", "तर्क", "coding decoding", "coding-decoding",
                                "कोडिंग डिकोडिंग", "blood relation", "रक्त संबंध", "syllogism", "न्याय निगमन",
                                "series", "shrinkhla", "श्रृंखला", "analogy", "सादृश्यता", "direction sense",
                                "दिशा", "seating arrangement", "बैठक व्यवस्था", "puzzle", "पहेली", "odd one out",
                                "विषम", "non verbal", "venn diagram", "calendar", "कैलेंडर", "clock", "घड़ी",
                                "ranking", "statement and conclusion", "कथन"]),
    "hindi": ("Hindi", ["hindi", "हिंदी", "हिन्दी", "vyakaran", "व्याकरण", "sandhi", "संधि", "samas", "समास", "alankar",
                        "अलंकार", "ras", "रस", "chhand", "छंद", "muhavare", "मुहावरे", "मुहावरा", "lokokti", "लोकोक्ति",
                        "paryayvachi", "पर्यायवाची", "vilom", "विलोम", "tatsam", "तत्सम", "tadbhav", "तद्भव", "sangya",
                        "संज्ञा", "sarvanam", "सर्वनाम", "visheshan", "विशेषण", "kriya", "क्रिया", "upsarg", "उपसर्ग",
                        "pratyay", "प्रत्यय", "kabir", "कबीर", "tulsidas", "तुलसीदास", "premchand", "प्रेमचंद", "kavita",
                        "कविता", "dohe", "दोहे", "nibandh", "निबंध"]),
    "english": ("English", ["english", "अंग्रेजी", "अंग्रेज़ी", "ਅੰਗਰੇਜ਼ੀ", "grammar", "tense", "tenses", "noun", "pronoun",
                            "verb", "adjective", "adverb", "preposition", "conjunction", "article a an the", "synonym",
                            "synonyms", "antonym", "antonyms", "idiom", "idioms", "phrasal verb", "active voice",
                            "passive voice", "direct indirect", "narration", "spelling", "vocabulary", "one word substitution",
                            "comprehension", "essay", "letter writing", "meaning in english", "translate into english",
                            "sentence correction", "error spotting", "shakespeare"]),
    "science": ("Science", ["science", "vigyan", "विज्ञान", "ਵਿਗਿਆਨ", "physics", "bhautiki", "भौतिकी", "chemistry",
                            "rasayan", "रसायन", "biology", "jeev vigyan", "जीव विज्ञान", "cell", "koshika", "कोशिका",
                            "atom", "parmanu", "परमाणु", "force", "bal", "बल", "electricity", "vidyut", "विद्युत",
                            "photosynthesis", "प्रकाश संश्लेषण", "acid", "base", "अम्ल", "क्षार", "newton", "gravity",
                            "गुरुत्वाकर्षण", "human body", "मानव शरीर", "vitamin", "विटामिन", "periodic table", "light",
                            "प्रकाश", "sound", "ध्वनि", "magnet", "चुंबक"]),
    "gk": ("General Knowledge", ["gk", "general knowledge", "samanya gyan", "सामान्य ज्ञान", "current affairs",
                                 "करंट अफेयर्स", "samsamayiki", "समसामयिकी", "capital", "rajdhani", "राजधानी", "award",
                                 "puraskar", "पुरस्कार", "sports", "khel", "खेल", "first in india", "national park",
                                 "राष्ट्रीय उद्यान", "festival", "tyohar", "त्योहार"]),
    "computer": ("Computer", ["computer", "कंप्यूटर", "कम्प्यूटर", "ms word", "excel", "internet", "इंटरनेट", "cpu",
                              "ram", "rom", "software", "hardware", "operating system", "shortcut key", "html", "network"]),
    "rajasthan": ("Rajasthan GK", ["rajasthan", "राजस्थान", "ਰਾਜਸਥਾਨ", "marwar", "मारवाड़", "mewar", "मेवाड़", "jaipur",
                                   "जयपुर", "jodhpur", "जोधपुर", "udaipur", "उदयपुर", "bikaner", "बीकानेर", "chittorgarh",
                                   "चित्तौड़गढ़", "rajputana", "राजपूताना"]),
}
GENERAL = "general"     # content and questions that belong to every teacher (e.g. study tips)
SUBJECT_KEYS = list(SUBJECTS)

# "<teacher> ko bulao" — said or typed, any language (same list in the app; rule 4)
CALL_WORDS = [
    "bulao", "bulaiye", "bula do", "bula lo", "bulana", "ko bulao", "se baat karao", "se baat karni hai",
    "se baat karwa do", "se padhna hai", "se padhao", "wale sir", "wali mam", "wali ma'am", "wale teacher",
    "wali teacher", "call karo", "connect karo", "connect me", "switch to", "call the", "talk to", "i want the",
    "बुलाओ", "बुलाइए", "बुला दो", "बुला लो", "से बात कराओ", "से बात करनी है", "से बात करवा दो", "से पढ़ना है",
    "वाले सर", "वाली मैम", "वाले टीचर", "वाली टीचर",
    "ਬੁਲਾਓ", "ਬੁਲਾ ਦਿਓ", "ਨਾਲ ਗੱਲ ਕਰਾਓ", "ਵਾਲੇ ਸਰ", "ਵਾਲੀ ਮੈਡਮ",
]
# replies that are never a reason to change teacher
STAY = {"ok", "okay", "hmm", "haan", "ha", "han", "yes", "no", "nahi", "thanks", "thank you", "thank", "acha", "accha",
        "achha", "theek", "theek hai", "samajh gaya", "samajh gayi", "aur batao", "aage batao", "next", "continue",
        "हाँ", "हां", "नहीं", "ठीक", "ठीक है", "अच्छा", "धन्यवाद", "और बताओ", "आगे बताओ", "समझ गया", "समझ गई"}

_W = re.compile(r"[^\wऀ-੿]+")


def _padded(text: str) -> str:
    return " " + _W.sub(" ", (text or "").lower()).strip() + " "


def _has(padded: str, phrase: str) -> bool:
    return f" {_padded(phrase).strip()} " in padded


def subject_label(key: str) -> str:
    return "General" if key == GENERAL else SUBJECTS.get(key, (key.title(), []))[0]


def clean_subjects(values) -> list[str]:
    out = []
    for v in values or []:
        k = str(v).strip().lower()
        if k in SUBJECTS or k == GENERAL:
            out.append(k)
    return list(dict.fromkeys(out))


def subject_candidates(text: str) -> list[str]:
    """Free keyword match → the subject(s) with the most hits ([] = no subject words)."""
    p = _padded(text)
    scores = {k: sum(1 for w in words if _has(p, w)) for k, (_, words) in SUBJECTS.items()}
    top = max(scores.values(), default=0)
    return [k for k, v in scores.items() if v == top] if top else []


def guess_subject_key(text: str) -> str | None:
    """The one subject with the most keyword hits (a tie = not sure)."""
    c = subject_candidates(text)
    return c[0] if len(c) == 1 else None


# ---------- faculty rows ----------

@dataclass
class Faculty:
    id: int
    institute_id: str
    name: str
    subjects: list[str]
    keywords: list[str]
    instructions: str = ""
    avatar_url: str | None = None
    voice_id: str | None = None
    active: bool = True

    def public(self) -> dict:
        """What the app gets with every answer (no instructions)."""
        return {"id": self.id, "name": self.name, "avatar_url": self.avatar_url, "voice_id": self.voice_id,
                "subjects": [subject_label(s) for s in self.subjects]}

    @property
    def subject_text(self) -> str:
        return ", ".join(subject_label(s) for s in self.subjects if s != GENERAL)


def _row(r) -> Faculty:
    return Faculty(r["id"], r["teacher_id"], r["name"], json.loads(r["subjects"] or "[]"),
                   json.loads(r["keywords"] or "[]"), r["instructions"] or "", r["avatar_url"], r["voice_id"],
                   bool(r["active"]))


def ensure_default(db: Database, institute_id: str) -> None:
    """Migration: an institute (old single-teacher app) without faculty gets one, from its own name and subject."""
    if db.one("SELECT 1 FROM faculty WHERE teacher_id = ?", (institute_id,)):
        return
    t = db.one("SELECT name, subject, avatar_url FROM teachers WHERE id = ?", (institute_id,))
    if t is None:
        return
    subjects = subject_candidates(t["subject"] or "") or [GENERAL]   # "Rajasthan History" → history + rajasthan
    db.execute("INSERT INTO faculty (teacher_id, name, subjects, keywords, avatar_url, active, sort, created_at) "
               "VALUES (?, ?, ?, '[]', ?, 1, 0, ?)",
               (institute_id, t["name"], json.dumps(subjects), t["avatar_url"], time.time()))


def ensure_all(db: Database) -> None:
    for r in db.all("SELECT id FROM teachers"):
        ensure_default(db, r["id"])


def list_faculty(db: Database, institute_id: str, active_only: bool = True) -> list[Faculty]:
    ensure_default(db, institute_id)
    sql = "SELECT * FROM faculty WHERE teacher_id = ?" + (" AND active = 1" if active_only else "") + " ORDER BY sort, id"
    return [_row(r) for r in db.all(sql, (institute_id,))]


def get(db: Database, institute_id: str, faculty_id: int) -> Faculty | None:
    r = db.one("SELECT * FROM faculty WHERE id = ? AND teacher_id = ?", (faculty_id, institute_id))
    return _row(r) if r else None


class FacultyError(ValueError):
    pass


def save(db: Database, institute_id: str, data: dict, faculty_id: int | None = None) -> Faculty:
    """Add or edit a faculty (admin panel / institute panel). No code needed for a new teacher or subject."""
    if not db.one("SELECT 1 FROM teachers WHERE id = ?", (institute_id,)):
        raise KeyError(institute_id)
    old = get(db, institute_id, faculty_id) if faculty_id else None
    if faculty_id and old is None:
        raise KeyError(faculty_id)
    name = str(data.get("name", old.name if old else "")).strip()[:80]
    if not name:
        raise FacultyError("Teacher name is needed")
    subjects = clean_subjects(data.get("subjects", old.subjects if old else []))
    if not subjects:
        raise FacultyError("Choose at least one subject")
    keywords = [str(k).strip()[:40] for k in data.get("keywords", old.keywords if old else []) if str(k).strip()][:40]
    instructions = str(data.get("instructions", old.instructions if old else "") or "").strip()[:2000]
    voice = str(data.get("voice_id", old.voice_id if old else "") or "").strip()[:80] or None
    active = 1 if data.get("active", old.active if old else True) else 0
    if old:
        if not active and old.active and len(list_faculty(db, institute_id)) <= 1:
            raise FacultyError("An app needs at least one active teacher")
        db.execute("UPDATE faculty SET name = ?, subjects = ?, keywords = ?, instructions = ?, voice_id = ?, active = ? "
                   "WHERE id = ?", (name, json.dumps(subjects), json.dumps(keywords, ensure_ascii=False), instructions,
                                    voice, active, faculty_id))
        return get(db, institute_id, faculty_id)
    n = db.one("SELECT COUNT(*) AS n FROM faculty WHERE teacher_id = ?", (institute_id,))["n"]
    cur = db.execute("INSERT INTO faculty (teacher_id, name, subjects, keywords, instructions, voice_id, active, sort, "
                     "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (institute_id, name, json.dumps(subjects), json.dumps(keywords, ensure_ascii=False), instructions,
                      voice, active, n, time.time()))
    return get(db, institute_id, cur.lastrowid)


def delete(db: Database, institute_id: str, faculty_id: int) -> None:
    """A teacher with history is only switched off (old answers keep their teacher); a new one is removed."""
    f = get(db, institute_id, faculty_id)
    if f is None:
        raise KeyError(faculty_id)
    others = [x for x in list_faculty(db, institute_id) if x.id != faculty_id]
    if not others:
        raise FacultyError("An app needs at least one active teacher")
    used = db.one("SELECT 1 FROM qa_history WHERE faculty_id = ? LIMIT 1", (faculty_id,))
    if used:
        db.execute("UPDATE faculty SET active = 0 WHERE id = ?", (faculty_id,))
    else:
        db.execute("DELETE FROM faculty WHERE id = ?", (faculty_id,))
    db.execute("UPDATE content_links SET faculty_id = NULL WHERE faculty_id = ?", (faculty_id,))
    db.execute("DELETE FROM common_attachments WHERE faculty_id = ?", (faculty_id,))
    db.execute("UPDATE students SET active_faculty_id = NULL WHERE active_faculty_id = ?", (faculty_id,))


def set_avatar(db: Database, institute_id: str, faculty_id: int, url: str) -> None:
    db.execute("UPDATE faculty SET avatar_url = ? WHERE id = ? AND teacher_id = ?", (url, faculty_id, institute_id))


# ---------- routing ----------

def covers(f: Faculty, subject: str) -> bool:
    return subject in f.subjects


def _keyword_faculty(text: str, facs: list[Faculty]) -> Faculty | None:
    """A faculty's own extra keywords (set in the panel), e.g. "RAS", "Patwari"."""
    p = _padded(text)
    hits = sorted(((sum(1 for k in f.keywords if _has(p, k)), f) for f in facs), key=lambda h: h[0], reverse=True)
    hits = [h for h in hits if h[0] > 0]
    if hits and (len(hits) == 1 or hits[0][0] > hits[1][0]):
        return hits[0][1]
    return None


def called_faculty(text: str, facs: list[Faculty]) -> Faculty | None:
    """"Maths wale sir ko bulao", "Sharma sir ko bulao", "connect me to the English teacher"."""
    p = _padded(text)
    if not any(_has(p, w) for w in CALL_WORDS):
        return None
    for f in facs:   # by name (without "sir" / "ma'am")
        name = re.sub(r"\b(sir|ma'?am|madam|mam|ji|teacher)\b", " ", f.name.lower())
        parts = [w for w in _padded(name).split() if len(w) > 2]
        if parts and all(f" {w} " in p for w in parts):
            return f
    subj = guess_subject_key(text)
    if subj:
        for f in facs:
            if covers(f, subj):
                return f
    return _keyword_faculty(text, facs)


def is_stay_reply(text: str) -> bool:
    s = _padded(text).strip()
    return s in STAY or len(s.split()) <= 1


@dataclass
class Route:
    faculty: Faculty
    switched: bool = False
    previous: Faculty | None = None
    reason: str = ""            # asked | subject | first
    subject: str | None = None


def route(db: Database, institute_id: str, student_id: int, question: str, model_subject: str | None = None,
          ai_subject=None) -> Route:
    """model_subject: the subject the safety check gave (our own AI checker), "none", or None (OpenAI's check gives none).
    ai_subject(question): asked only when that and the free keyword match are both unsure (it rides on the search
    keyword call the AI teacher makes anyway, and is remembered per question — no extra AI call)."""
    facs = list_faculty(db, institute_id)
    if not facs:
        raise FacultyError("No teacher")
    st = db.one("SELECT active_faculty_id FROM students WHERE id = ?", (student_id,))
    current = next((f for f in facs if st and f.id == st["active_faculty_id"]), None)
    subject = model_subject if model_subject in SUBJECTS else None
    if subject is None and model_subject != "none":
        cands = subject_candidates(question)
        subject = cands[0] if len(cands) == 1 else None
        if len(cands) > 1:   # e.g. "Rajasthan ka itihas": history + Rajasthan GK → the teacher who covers most of them
            best = sorted(facs, key=lambda f: -sum(covers(f, c) for c in cands))
            if best and sum(covers(best[0], c) for c in cands) > (sum(covers(best[1], c) for c in cands) if len(best) > 1 else 0):
                subject = next(c for c in cands if covers(best[0], c))

    target, reason = None, ""
    called = called_faculty(question, facs) if len(facs) > 1 else None
    if called:
        target, reason = called, "asked"
    elif len(facs) > 1 and not is_stay_reply(question):
        own = _keyword_faculty(question, facs)
        if subject is None and not own and model_subject != "none" and ai_subject is not None:
            try:
                got = ai_subject(question)
            except Exception:
                got = None
            subject = got if got in SUBJECTS else None
        if own and own is not current:
            target, reason = own, "subject"
        elif subject and not (current and covers(current, subject)) and not own:
            target = next((f for f in facs if covers(f, subject)), None)
            reason = "subject" if target else ""
    if target is None:
        target, reason = current or next((f for f in facs if subject and covers(f, subject)), None) or facs[0], \
            ("" if current else "first")
    switched = current is not None and target.id != current.id
    if not current or switched:
        db.execute("UPDATE students SET active_faculty_id = ? WHERE id = ?", (target.id, student_id))
    return Route(target, switched, current if switched else None, reason if (switched or not current) else "", subject)


HANDOVER = {
    "en": "This is a {subject} question — let me connect you to {name}.",
    "hi": "यह {subject} का सवाल है — मैं आपको {name} से जोड़ रहा हूँ।",
    "hi-Latn": "Yeh {subject} ka sawal hai — main aapko {name} se jod raha hoon.",
    "pa": "ਇਹ {subject} ਦਾ ਸਵਾਲ ਹੈ — ਮੈਂ ਤੁਹਾਨੂੰ {name} ਨਾਲ ਜੋੜ ਰਿਹਾ ਹਾਂ।",
}
HANDOVER_ASKED = {
    "en": "Sure — connecting you to {name}.",
    "hi": "ज़रूर — मैं आपको {name} से जोड़ रहा हूँ।",
    "hi-Latn": "Zaroor — main aapko {name} se jod raha hoon.",
    "pa": "ਜ਼ਰੂਰ — ਮੈਂ ਤੁਹਾਨੂੰ {name} ਨਾਲ ਜੋੜ ਰਿਹਾ ਹਾਂ।",
}


def handover_line(r: Route, lang: str) -> str:
    """The short fixed line the old teacher says before the new face appears (no AI call, like a call transfer)."""
    if not r.switched:
        return ""
    table = HANDOVER_ASKED if r.reason == "asked" or not r.subject else HANDOVER
    text = table.get(lang) or table.get(lang.split("-")[0]) or table["en"]
    return text.format(name=r.faculty.name, subject=subject_label(r.subject) if r.subject else "")
