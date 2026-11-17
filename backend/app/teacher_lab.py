"""Multi-teacher test lab: the owner brief's 7 checks, run on a throw-away database with 5 prototype teachers
(History, Hindi, English, Maths, Reasoning), like the safety lab. No real student or institute is touched.

mode "free": subject from the free keyword match (what runs when the AI is off) — costs nothing.
mode "ai":   subject from the real small model (our own safety checker, or — with OpenAI's free check — the search
             keyword call when the keywords are unsure), and the real file classifier. A few small-model calls; needs
             the AI key on the server.
"""
import json
import os
import tempfile
import time

from .db import Database
from .services import faculty as fac, library

TEACHERS = [("Rathore Sir", ["history", "rajasthan"]), ("Sharma Ma'am", ["hindi"]), ("Mr. Joseph", ["english"]),
            ("Gupta Sir", ["maths"]), ("Verma Sir", ["reasoning"])]

FILES = {   # file name → (text, expected subject). One has no subject in its name: the classifier decides.
    "History/haldighati.txt": ("हल्दीघाटी का युद्ध 18 जून 1576 को महाराणा प्रताप और अकबर की सेना के बीच हुआ। "
                               "मुगल सेना का नेतृत्व मान सिंह ने किया। महाराणा प्रताप का घोड़ा चेतक प्रसिद्ध है।", "history"),
    "hindi_vyakaran_sandhi.txt": ("संधि: दो वर्णों के मेल से होने वाले विकार को संधि कहते हैं। स्वर संधि के पाँच भेद हैं: "
                                  "दीर्घ, गुण, वृद्धि, यण और अयादि। विद्या + आलय = विद्यालय (दीर्घ संधि)।", "hindi"),
    "English Grammar - Tenses.txt": ("Tenses: the present perfect tense uses has or have with the past participle. "
                                     "Example: She has finished her homework. The passive voice of this sentence is: "
                                     "Her homework has been finished by her.", "english"),
    "maths/percentage.txt": ("Percentage: to find x percent of y, multiply y by x and divide by 100. Profit percentage = "
                             "profit / cost price x 100. If the cost price is 400 and the selling price is 500, the "
                             "profit percentage is 25.", "maths"),
    "chapter-7.txt": ("Coding-decoding: in a certain code language CAT is written as DBU, each letter moves one step "
                      "forward. Blood relation and series questions also appear in the reasoning paper. Coding decoding "
                      "puzzle practice set.", "reasoning"),
}

QUESTIONS = [   # (question, expected subject)
    ("सर, मुझे राजस्थान का इतिहास पढ़ना है", "history"),
    ("Haldighati ka yudh kab hua tha?", "history"),
    ("Sir, coding-decoding ka ek reasoning sawal samjhaiye", "reasoning"),
    ("What is the passive voice of 'She has finished her homework'?", "english"),
    ("400 ka 25 percent kitna hota hai?", "maths"),
    ("संधि के कितने भेद होते हैं?", "hindi"),
]


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"check": name, "passed": bool(ok), "detail": detail}


def run(mode: str = "free", settings=None) -> list[dict]:
    tmp = tempfile.mkdtemp(prefix="teacher-lab-")
    db = Database(os.path.join(tmp, "lab.db"))
    side_llm = moderator = ai_subject = None
    if mode == "ai":
        from . import ai_setup
        if not getattr(settings, "llm_api_key", ""):
            raise RuntimeError("The AI check needs the AI key on the server (LLM_API_KEY)")
        ai = ai_setup.build(db, settings)
        side_llm, moderator, ai_subject = ai.side_llm, ai.moderator, ai.tutor.subject_of
    db.execute("INSERT INTO teachers (id, name, subject) VALUES ('lab', 'Lab Institute', 'History')")
    db.execute("INSERT INTO teachers (id, name, subject) VALUES ('other', 'Other Institute', 'Maths')")
    fac.ensure_default(db, "lab")
    first = fac.list_faculty(db, "lab")[0]
    fac.save(db, "lab", {"name": TEACHERS[0][0], "subjects": TEACHERS[0][1]}, first.id)
    facs = {TEACHERS[0][1][0]: first.id}
    for name, subs in TEACHERS[1:]:
        facs[subs[0]] = fac.save(db, "lab", {"name": name, "subjects": subs}).id
    sid = db.execute("INSERT INTO students (teacher_id, phone) VALUES ('lab', '9000000001')").lastrowid

    def subject_of(q: str):
        """What the live app has before routing: the subject from our own AI checker (None with OpenAI's check)."""
        if moderator is None:
            return None
        return moderator.check_input(q).subject

    out = []
    # 1 · subject detection
    got = []
    for q, want in QUESTIONS:
        s = subject_of(q)
        found = [s] if s and s != "none" else fac.subject_candidates(q)
        if len(found) != 1 and ai_subject and s != "none":   # keywords unsure → the search-keyword call says it
            got = ai_subject(q)
            found = [got] if got else found
        got.append((q, want, found))
    teacher_of = {subs[0]: subs for _, subs in TEACHERS}
    bad = [f"“{q}” → {', '.join(s) or 'not sure'} (should be {w})" for q, w, s in got
           if not s or not set(s) <= set(teacher_of[w])]
    out.append(_check("1. Subject is found", not bad, "; ".join(bad) or f"{len(got)}/{len(got)} questions right"))

    # 2 · the right teacher is activated (fresh student each time)
    bad = []
    for i, (q, want) in enumerate(QUESTIONS):
        s2 = db.execute("INSERT INTO students (teacher_id, phone) VALUES ('lab', ?)", (f"91{i:08d}",)).lastrowid
        r = fac.route(db, "lab", s2, q, subject_of(q), ai_subject)
        if r.faculty.id != facs[want]:
            bad.append(f"“{q}” → {r.faculty.name}")
    out.append(_check("2. Right teacher answers", not bad, "; ".join(bad) or "every question went to its subject teacher"))

    # 3 · switching is smooth: sticky on "ok", switch on a new subject, switch on request, handover line
    steps = [("Haldighati ka yudh kab hua tha?", "history", False), ("ok", "history", False),
             ("aur batao", "history", False), ("Sir, coding-decoding ka ek reasoning sawal samjhaiye", "reasoning", True),
             ("theek hai", "reasoning", False), ("Maths wale sir ko bulao", "maths", True),
             ("English teacher ko bulao", "english", True)]
    bad = []
    for q, want, should_switch in steps:
        r = fac.route(db, "lab", sid, q, subject_of(q) if len(q.split()) > 2 else None, ai_subject)
        line = fac.handover_line(r, "hi-Latn")
        if r.faculty.id != facs[want] or r.switched != should_switch or (should_switch and not line):
            bad.append(f"“{q}” → {r.faculty.name}{' (switched)' if r.switched else ''}")
    out.append(_check("3. Switching is smooth", not bad,
                      "; ".join(bad) or "stays on “ok / aur batao”, switches on a new subject or when asked, with a handover line"))

    # 4 · all content in one place (one upload, many files)
    links = [library.upload(db, "lab", n, txt.encode(), side_llm=side_llm, moderator=moderator,
                            **({} if mode == "ai" else {"subject": None}))
             for n, (txt, _) in FILES.items()]
    if mode != "ai":   # free mode: the file without a subject in its name is assigned by the admin in one click
        pend = [l for l in links if l["status"] == "pending"]
        for l in pend:
            library.assign(db, "lab", l["id"], "reasoning", None)
    lst = library.list_links(db, "lab")
    out.append(_check("4. All content in one library", lst["total"] == len(FILES),
                      f"{lst['total']} files in the institute’s one library"))

    # 5 · mapped to the right subject and teacher
    by_title = {i["title"]: i for i in library.list_links(db, "lab")["items"]}
    bad = [f"{n.split('/')[-1]} → {by_title[n.split('/')[-1]]['subject'] or 'pending'}" for n, (_, w) in FILES.items()
           if by_title[n.split("/")[-1]]["subject"] != w]
    counts = library.faculty_stats(db, "lab")
    bad += [f"{fac.get(db, 'lab', fid).name} has {n} files" for fid, n in counts.items() if n != 1]
    note = "" if mode == "ai" else " (file without a subject in its name: “Pending check”, then one click)"
    out.append(_check("5. Content goes to the right teacher", not bad, "; ".join(bad) or "every file on its teacher" + note))

    # 6 · each teacher answers only from their own content; institutes never mix; same file stored once
    bad = []
    maths = fac.get(db, "lab", facs["maths"])
    hist = fac.get(db, "lab", facs["history"])
    if library.search(db, maths, ["Haldighati yudh Maharana Pratap"])[0]:
        bad.append("Maths teacher found History notes")
    if not library.search(db, maths, ["profit percentage cost price"])[0]:
        bad.append("Maths teacher did not find his own notes")
    if not library.search(db, hist, ["हल्दीघाटी युद्ध"])[0]:
        bad.append("History teacher did not find his own notes")
    files_before = db.one("SELECT COUNT(*) AS n FROM content_files")["n"]
    library.upload(db, "other", "percentage.txt", FILES["maths/percentage.txt"][0].encode(), subject="maths")
    if db.one("SELECT COUNT(*) AS n FROM content_files")["n"] != files_before:
        bad.append("the same file was stored twice")
    other = fac.list_faculty(db, "other")[0]
    if library.search(db, other, ["हल्दीघाटी युद्ध"])[0]:
        bad.append("another institute found this institute’s notes")
    out.append(_check("6. Each teacher uses only their own content", not bad,
                      "; ".join(bad) or "own notes only · institutes kept apart · same file stored once"))

    # 7 · a new teacher and new content without code
    geo = fac.save(db, "lab", {"name": "Meena Ma'am", "subjects": ["geography"]})
    library.upload(db, "lab", "Geography/rivers.txt", "चंबल नदी राजस्थान की एकमात्र बारहमासी नदी है। माही नदी कर्क रेखा को "
                   "दो बार काटती है। थार मरुस्थल पश्चिम में है।".encode(), moderator=moderator, side_llm=side_llm)
    r = fac.route(db, "lab", sid, "चंबल नदी के बारे में बताइए, भूगोल", subject_of("चंबल नदी के बारे में बताइए, भूगोल"),
                  ai_subject)
    hits = library.search(db, geo, ["चंबल नदी"])[0]
    ok = r.faculty.id == geo.id and bool(hits)
    out.append(_check("7. New teacher and content without code", ok,
                      "added from the panel, new file mapped, questions reach the new teacher" if ok else
                      f"question went to {r.faculty.name}; notes found: {bool(hits)}"))
    return out


def run_and_save(db: Database, by: str, mode: str = "free", settings=None) -> dict:
    t0 = time.time()
    results = run(mode, settings)
    passed = sum(1 for r in results if r["passed"])
    db.execute("INSERT INTO teacher_lab_runs (at, by, mode, passed, total, results) VALUES (?, ?, ?, ?, ?, ?)",
               (time.time(), by, mode, passed, len(results), json.dumps(results, ensure_ascii=False)))
    return {**last(db), "seconds": round(time.time() - t0, 1)}


def last(db: Database) -> dict:
    rows = db.all("SELECT * FROM teacher_lab_runs ORDER BY id DESC LIMIT 10")
    runs = [{"at": r["at"], "by": r["by"], "mode": r["mode"], "passed": r["passed"], "total": r["total"]} for r in rows]
    return {"last": {**runs[0], "results": json.loads(rows[0]["results"])} if rows else None, "runs": runs}
