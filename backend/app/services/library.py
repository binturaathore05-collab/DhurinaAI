"""One content library per institute, files stored once across the platform, and Dhurina's Common Library.

Storage model (also used for de-duplication and the Common Library):
  content_files   one row per unique file (fingerprint of the bytes + of the normalized text), with its text
  content_chunks  the search pieces of that file (made once)
  content_links   who uses the file: an institute (owner = institute id) or the Common Library (owner = "common"),
                  with that owner's own title, subject, teacher and status
  common_attachments  a Common Library subject linked to one institute teacher (a link, not a copy)

Subject of an uploaded file, in this order: chosen at upload → a subject in the file / folder name → one small-model
call on the first pages (once per file, ever) → not sure = "pending check" for the admin.
Every new file is safety-checked before it goes live. An institute is never told that a file already existed.
"""
import hashlib
import io
import json
import re
import time
import zipfile
from dataclasses import dataclass

from ..db import Database
from . import faculty as fac
from .knowledge import Hit, chunk_text, tokenize, bm25

COMMON = "common"
MAX_BYTES = 40_000_000
KINDS = {".pdf": "pdf", ".txt": "txt", ".md": "txt", ".docx": "docx"}


class LibraryError(ValueError):
    pass


# ---------- reading files ----------

def kind_of(filename: str) -> str:
    m = re.search(r"\.[A-Za-z0-9]+$", filename or "")
    k = KINDS.get(m.group().lower()) if m else None
    if not k:
        raise LibraryError("Upload PDF, Word (.docx) or text files")
    return k


@dataclass
class Extracted:
    text: str
    pages: int = 0          # pages in the PDF (0 for Word / text)
    pages_read: int = 0     # pages that gave text
    unclear: float = 0.0    # share of broken characters (�, boxes, a vowel sign with no letter before it)


# Hindi PDFs: the plain PDF readers drop or scramble matras and joined letters (क्ष, ज्ञ, प्र …).
# So every reader that is there is tried, and the one that gives the cleanest, most complete text wins:
# poppler (pdftotext, in the server image: best for Hindi) → pdfium → pypdf.
_BAD = re.compile(r"[\ufffd\ue000-\uf8ff\x00-\x08\x0b\x0e-\x1f\u2261]")
_SIGN = "\u0901-\u0903\u093e-\u094d\u0962\u0963"
_ORPHAN = re.compile(rf"(?:^|(?<=[\s(\"'“‘\-]))[{_SIGN}]", re.M)
_CONS = "\u0915-\u0939\u0958-\u095f"
_I_BEFORE = re.compile(rf"(?<![{_CONS}\u093c])\u093f\s?([{_CONS}]\u093c?(?:\u094d[{_CONS}]\u093c?)*)")
_LETTER = re.compile(r"[\w\u0900-\u0a7f]")


def unclear_share(text: str) -> float:
    letters = len(_LETTER.findall(text))
    return (len(_BAD.findall(text)) + len(_ORPHAN.findall(text))) / letters if letters else 0.0


def clean_text(text: str) -> str:
    """Tidy what a PDF reader gave: "ि" written before its letter goes after it (िकया → किया), markdown marks
    left in AI-made notes (**bold**, ## headings) go, extra spaces go."""
    text = _I_BEFORE.sub(lambda m: m.group(1) + "\u093f", text)
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s+", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _pages_poppler(data: bytes) -> list[str] | None:
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        try:
            out = subprocess.run([exe, "-q", "-enc", "UTF-8", f.name, "-"], capture_output=True, timeout=120)
        except Exception:
            return None
    if out.returncode != 0:
        return None
    pages = out.stdout.decode("utf-8", "replace").split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


def _pages_pdfium(data: bytes) -> list[str] | None:
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(data)
        return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    except Exception:
        return None


def _pages_pypdf(data: bytes) -> list[str] | None:
    try:
        from pypdf import PdfReader
        return [(p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages]
    except Exception:
        return None


def read_pdf(data: bytes) -> Extracted:
    found = []
    for rank, reader in enumerate((_pages_poppler, _pages_pdfium, _pages_pypdf)):
        pages = reader(data)
        if pages is None:
            continue
        text = clean_text("\n\n".join(p.strip() for p in pages))
        letters = len(_LETTER.findall(text))
        bad = unclear_share(text)
        found.append((letters * (1 - 5 * bad), rank, Extracted(text, len(pages), sum(1 for p in pages if p.strip()), bad)))
    if not found:
        raise LibraryError("Could not open this PDF")
    best = max(f[0] for f in found)
    # near the best (within 1%), the better reader wins: poppler keeps Hindi words and spaces right
    return min((f for f in found if f[0] >= best * 0.99), key=lambda f: f[1])[2]


def read_file(kind: str, data: bytes) -> Extracted:
    if kind == "pdf":
        return read_pdf(data)
    if kind == "txt":
        for enc in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                text = clean_text(data.decode(enc))
                return Extracted(text, unclear=unclear_share(text))
            except UnicodeDecodeError:
                continue
        raise LibraryError("Could not read this text file")
    try:
        xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")
    except Exception:
        raise LibraryError("Could not open this Word file")
    xml = re.sub(r"</w:p>", "\n\n", xml)
    text = clean_text(re.sub(r"<[^>]+>", "", xml).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
    return Extracted(text, unclear=unclear_share(text))


def extract_text(kind: str, data: bytes) -> str:
    return read_file(kind, data).text


UNCLEAR_LIMIT = 0.02   # more than 2 in 100 letters broken → the file waits for a person ("Text unclear")


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def fingerprints(data: bytes, text: str) -> tuple[str, str]:
    return hashlib.sha256(data).hexdigest(), hashlib.sha256(normalized(text).encode()).hexdigest()


# ---------- classification ----------

CLASSIFY = """You sort study material for an Indian coaching institute. Read the start of the file and say which ONE
subject it teaches. Subjects: {keys}. Use "general" only for material that belongs to every subject (study tips,
exam pattern). If it mixes subjects or you are not sure, answer "unsure".
Return JSON only: {{"subject": one of the subjects, "general" or "unsure"}}"""


def ai_subject(side_llm, text: str) -> str:
    """One small-model call on the first pages. Any trouble = "unsure" (the admin decides in one click)."""
    if side_llm is None:
        return "unsure"
    try:
        out = side_llm.chat_json(CLASSIFY.format(keys=fac.SUBJECT_KEYS), text[:4000])
        s = str(out.get("subject", "")).strip().lower()
    except Exception:
        return "unsure"
    return s if s in fac.SUBJECTS or s == fac.GENERAL else "unsure"


def name_subject(path: str) -> str | None:
    """A subject named in the file or folder name: "Maths/Percentage.pdf", "hindi_vyakaran.docx"."""
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", path or "")
    return fac.guess_subject_key(re.sub(r"[_\-/\\.]+", " ", stem))


# ---------- safety ----------

def safety_scan(moderator, text: str) -> tuple[str, str | None]:
    """Three windows (start, middle, end), checked like an AI answer, before anything goes live."""
    if moderator is None:
        return "ok", None
    from . import moderation
    n = len(text)
    windows = [text[:6000]] if n <= 6000 else [text[:6000], text[n // 2 - 3000: n // 2 + 3000], text[-6000:]]
    try:
        for w in windows:
            v = moderator.check(w, "output")
            if not v.safe:
                return "blocked", v.category
    except moderation.Unavailable:
        return "retry", "safety check could not run"
    return "ok", None


# ---------- upload ----------

def _status(subject: str | None, file_row, accepted=0) -> str:
    """blocked (safety) > checking (safety check could not run) > unclear (broken text, until a person accepts it)
    > pending (subject not decided) > live."""
    if file_row["safety"] == "blocked":
        return "blocked"
    if file_row["safety"] == "retry":
        return "checking"
    if (file_row["unclear"] or 0) > UNCLEAR_LIMIT and not accepted:
        return "unclear"
    return "live" if subject else "pending"


def upload(db: Database, owner: str, filename: str, data: bytes, *, subject: str | None = None,
           faculty_id: int | None = None, allow_common: bool = False, by: str = "", side_llm=None,
           moderator=None) -> dict:
    """Add one file to an institute's library (or the Common Library). Returns the link as the panel shows it."""
    if not data:
        raise LibraryError("The file is empty")
    if len(data) > MAX_BYTES:
        raise LibraryError("A file can be at most 40 MB")
    kind = kind_of(filename)
    if owner != COMMON and not db.one("SELECT 1 FROM teachers WHERE id = ?", (owner,)):
        raise KeyError(owner)
    f_given = fac.get(db, owner, int(faculty_id)) if faculty_id and owner != COMMON else None
    if faculty_id and owner != COMMON and f_given is None:
        raise LibraryError("Unknown teacher")
    sha = hashlib.sha256(data).hexdigest()
    row = db.one("SELECT * FROM content_files WHERE sha256 = ?", (sha,))
    if row is None:
        got = read_file(kind, data)
        text = got.text
        if len(normalized(text)) < 20:
            raise LibraryError("No readable text in this file (a scanned PDF needs typed text for now)")
        _, th = fingerprints(data, text)
        row = db.one("SELECT * FROM content_files WHERE text_hash = ?", (th,))   # same text, other bytes
        if row is None:
            safety, note = safety_scan(moderator, text)
            with db.tx() as c:
                cur = c.execute("INSERT INTO content_files (sha256, text_hash, size, kind, text, safety, safety_note, "
                                "created_at, pages, pages_read, unclear) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (sha, th, len(data), kind, text, safety, note, time.time(), got.pages, got.pages_read,
                                 round(got.unclear, 4)))
                fid = cur.lastrowid
                for ch in chunk_text(text):
                    c.execute("INSERT INTO content_chunks (file_id, text) VALUES (?, ?)", (fid, ch))
            row = db.one("SELECT * FROM content_files WHERE id = ?", (fid,))

    # subject + teacher for THIS owner: chosen → file name → AI (once per file) → pending
    chosen = subject if subject in fac.SUBJECTS or subject == fac.GENERAL else None
    if f_given and not chosen:
        chosen = next((s for s in f_given.subjects), None)
    how = "upload" if (chosen or f_given) else None
    if not chosen:
        chosen = name_subject(filename)
        how = "name" if chosen else None
    if not chosen:
        guess = row["ai_subject"]
        if guess is None:
            guess = ai_subject(side_llm, row["text"])
            db.execute("UPDATE content_files SET ai_subject = ? WHERE id = ?", (guess, row["id"]))
        if guess != "unsure":
            chosen, how = guess, "ai"
    title = (filename or "file").replace("\\", "/").split("/")[-1][:160]
    old = db.one("SELECT id FROM content_links WHERE file_id = ? AND owner = ?", (row["id"], owner))
    if old:   # already in this library: keep the existing link (no second copy), just answer "uploaded"
        return link_view(db, old["id"])
    cur = db.execute(
        "INSERT INTO content_links (file_id, owner, title, subject, faculty_id, assigned_by, status, allow_common, "
        "uploaded_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], owner, title, chosen, f_given.id if f_given else None, how, _status(chosen, row),
         int(bool(allow_common)), by, time.time()))
    return link_view(db, cur.lastrowid)


def link_view(db: Database, link_id: int) -> dict:
    r = db.one("SELECT l.*, f.kind, f.size, f.safety, f.safety_note, f.pages, f.pages_read, f.unclear FROM content_links l "
               "JOIN content_files f ON f.id = l.file_id WHERE l.id = ?", (link_id,))
    if r is None:
        raise KeyError(link_id)
    out = {k: r[k] for k in ("id", "owner", "title", "subject", "faculty_id", "assigned_by", "status", "allow_common",
                             "kind", "size", "created_at")}
    out["subject_label"] = fac.subject_label(r["subject"]) if r["subject"] else None
    out["safety_note"] = r["safety_note"] if r["status"] in ("blocked", "checking") else None
    out.update(pages=r["pages"] or 0, pages_read=r["pages_read"] or 0, unclear_percent=round((r["unclear"] or 0) * 100, 1),
               accepted=bool(r["accepted"]))
    return out


def _link(db: Database, owner: str, link_id: int):
    r = db.one("SELECT * FROM content_links WHERE id = ? AND owner = ?", (link_id, owner))
    if r is None:
        raise KeyError(link_id)
    return r


def list_links(db: Database, owner: str, status: str = "", subject: str = "", q: str = "") -> dict:
    rows = db.all("SELECT id FROM content_links WHERE owner = ? ORDER BY id DESC", (owner,))
    items = [link_view(db, r["id"]) for r in rows]
    counts = {s: sum(1 for i in items if i["status"] == s) for s in ("live", "pending", "unclear", "blocked", "checking")}
    if status:
        items = [i for i in items if i["status"] == status]
    if subject:
        items = [i for i in items if (i["subject"] or "") == subject]
    if q:
        items = [i for i in items if q.lower() in i["title"].lower()]
    return {"items": items, "counts": counts, "total": len(rows)}


def assign(db: Database, owner: str, link_id: int, subject: str | None, faculty_id: int | None) -> dict:
    """Manual subject / teacher (also clears "pending check"). A teacher alone means that teacher's first subject."""
    r = _link(db, owner, link_id)
    f = fac.get(db, owner, int(faculty_id)) if faculty_id and owner != COMMON else None
    if faculty_id and owner != COMMON and f is None:
        raise LibraryError("Unknown teacher")
    subject = subject if subject in fac.SUBJECTS or subject == fac.GENERAL else None
    if f and not subject:
        subject = f.subjects[0]
    if not subject:
        raise LibraryError("Choose a subject or a teacher")
    frow = db.one("SELECT * FROM content_files WHERE id = ?", (r["file_id"],))
    db.execute("UPDATE content_links SET subject = ?, faculty_id = ?, assigned_by = 'admin', status = ? WHERE id = ?",
               (subject, f.id if f else None, _status(subject, frow, r["accepted"]), link_id))
    return link_view(db, link_id)


def preview(db: Database, owner: str, link_id: int, offset: int = 0, chars: int = 60000) -> dict:
    """The file's text as the teachers use it — the whole of it, in parts for very big books."""
    r = _link(db, owner, link_id)
    f = db.one("SELECT text FROM content_files WHERE id = ?", (r["file_id"],))
    total = len(f["text"])
    offset = max(0, min(int(offset), total))
    end = min(total, offset + max(1000, min(int(chars), 200000)))
    return {**link_view(db, link_id), "text": f["text"][offset:end], "offset": offset, "total_chars": total,
            "next_offset": end if end < total else None, "more": end < total}


def accept(db: Database, owner: str, link_id: int) -> dict:
    """A person read the "Text unclear" file and says it is good enough: it can go live."""
    r = _link(db, owner, link_id)
    frow = db.one("SELECT * FROM content_files WHERE id = ?", (r["file_id"],))
    db.execute("UPDATE content_links SET accepted = 1, status = ? WHERE id = ?",
               (_status(r["subject"], frow, 1), link_id))
    return link_view(db, link_id)


def _drop_file_if_unused(db: Database, file_id: int) -> None:
    if not db.one("SELECT 1 FROM content_links WHERE file_id = ?", (file_id,)):
        with db.tx() as c:
            c.execute("DELETE FROM content_chunks WHERE file_id = ?", (file_id,))
            c.execute("DELETE FROM content_files WHERE id = ?", (file_id,))


def remove(db: Database, owner: str, link_id: int) -> None:
    """Removes only this owner's link. The stored file goes when nobody links to it any more."""
    r = _link(db, owner, link_id)
    db.execute("DELETE FROM content_links WHERE id = ?", (link_id,))
    _drop_file_if_unused(db, r["file_id"])


def replace(db: Database, owner: str, link_id: int, filename: str, data: bytes, **kw) -> dict:
    """A new version of a file: keeps the old link's subject and teacher."""
    r = _link(db, owner, link_id)
    new = upload(db, owner, filename, data, subject=r["subject"], faculty_id=r["faculty_id"],
                 allow_common=bool(r["allow_common"]), **kw)
    if new["id"] != link_id:
        db.execute("DELETE FROM content_links WHERE id = ?", (link_id,))
        _drop_file_if_unused(db, r["file_id"])
    return new


def edit_text(db: Database, owner: str, link_id: int, text: str, **kw) -> dict:
    """Edit the text of a file: saved as a new (text) file for this owner only; other users keep the original."""
    r = _link(db, owner, link_id)
    title = re.sub(r"\.[A-Za-z0-9]+$", "", r["title"]) + ".txt"
    return replace(db, owner, link_id, title, text.encode("utf-8"), **kw)


def recheck(db: Database, link_id: int, moderator) -> dict:
    """Run the safety check again for a file whose check could not run."""
    r = db.one("SELECT * FROM content_links WHERE id = ?", (link_id,))
    if r is None:
        raise KeyError(link_id)
    f = db.one("SELECT * FROM content_files WHERE id = ?", (r["file_id"],))
    if f["safety"] == "retry":
        safety, note = safety_scan(moderator, f["text"])
        db.execute("UPDATE content_files SET safety = ?, safety_note = ? WHERE id = ?", (safety, note, f["id"]))
        f = db.one("SELECT * FROM content_files WHERE id = ?", (f["id"],))
        for l in db.all("SELECT id, subject, accepted FROM content_links WHERE file_id = ?", (f["id"],)):
            db.execute("UPDATE content_links SET status = ? WHERE id = ?", (_status(l["subject"], f, l["accepted"]), l["id"]))
    return link_view(db, link_id)


# ---------- Common Library ----------

def promote(db: Database, institute: str, link_id: int, by: str) -> dict:
    """Super Admin: put an institute's file into the Common Library (only if its uploader allowed it)."""
    r = _link(db, institute, link_id)
    if not r["allow_common"]:
        raise LibraryError("The uploader did not allow this file in the Common Library")
    old = db.one("SELECT id FROM content_links WHERE file_id = ? AND owner = ?", (r["file_id"], COMMON))
    if old:
        return link_view(db, old["id"])
    frow = db.one("SELECT * FROM content_files WHERE id = ?", (r["file_id"],))
    cur = db.execute("INSERT INTO content_links (file_id, owner, title, subject, assigned_by, status, uploaded_by, "
                     "created_at, accepted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (r["file_id"], COMMON, r["title"], r["subject"], r["assigned_by"],
                      _status(r["subject"], frow, r["accepted"]), by, time.time(), r["accepted"]))
    return link_view(db, cur.lastrowid)


def attach(db: Database, institute: str, faculty_id: int, subject: str, by: str) -> None:
    f = fac.get(db, institute, faculty_id)
    if f is None:
        raise KeyError(faculty_id)
    if subject not in fac.SUBJECTS and subject != fac.GENERAL:
        raise LibraryError("Unknown subject")
    db.execute("INSERT OR IGNORE INTO common_attachments (faculty_id, subject, attached_by, at) VALUES (?, ?, ?, ?)",
               (faculty_id, subject, by, time.time()))


def detach(db: Database, institute: str, faculty_id: int, subject: str) -> None:
    if fac.get(db, institute, faculty_id) is None:
        raise KeyError(faculty_id)
    db.execute("DELETE FROM common_attachments WHERE faculty_id = ? AND subject = ?", (faculty_id, subject))


def attachments(db: Database, institute: str) -> list[dict]:
    rows = db.all("SELECT a.* FROM common_attachments a JOIN faculty f ON f.id = a.faculty_id WHERE f.teacher_id = ? "
                  "ORDER BY a.id", (institute,))
    return [{"faculty_id": r["faculty_id"], "subject": r["subject"], "subject_label": fac.subject_label(r["subject"]),
             "attached_by": r["attached_by"], "at": r["at"]} for r in rows]


def common_subjects(db: Database) -> list[dict]:
    rows = db.all("SELECT subject, COUNT(*) AS n FROM content_links WHERE owner = ? AND status = 'live' "
                  "GROUP BY subject", (COMMON,))
    return [{"subject": r["subject"], "label": fac.subject_label(r["subject"]), "files": r["n"]} for r in rows]


# ---------- search for one teacher ----------

def _only_teacher(db: Database, f: fac.Faculty) -> bool:
    """A solo teacher (an institute with one active teacher) uses the whole library, whatever the subject."""
    return len(fac.list_faculty(db, f.institute_id)) == 1


def _own_rows(db: Database, f: fac.Faculty) -> list:
    """This teacher's content: files fixed to them, files of their subjects with no fixed teacher, and general."""
    if _only_teacher(db, f):
        return db.all("SELECT c.id, c.text, l.title FROM content_chunks c JOIN content_links l ON l.file_id = c.file_id "
                      "WHERE l.owner = ? AND l.status = 'live'", (f.institute_id,))
    subs = list(f.subjects) + [fac.GENERAL]
    marks = ",".join("?" * len(subs))
    return db.all(
        "SELECT c.id, c.text, l.title FROM content_chunks c JOIN content_links l ON l.file_id = c.file_id "
        f"WHERE l.owner = ? AND l.status = 'live' AND (l.faculty_id = ? OR (l.faculty_id IS NULL AND l.subject IN ({marks})) "
        "OR l.subject = ?)", (f.institute_id, f.id, *subs, fac.GENERAL))


def _common_rows(db: Database, f: fac.Faculty) -> list:
    subs = [r["subject"] for r in db.all("SELECT subject FROM common_attachments WHERE faculty_id = ?", (f.id,))]
    if not subs:
        return []
    marks = ",".join("?" * len(subs))
    return db.all("SELECT c.id, c.text, l.title FROM content_chunks c JOIN content_links l ON l.file_id = c.file_id "
                  f"WHERE l.owner = ? AND l.status = 'live' AND l.subject IN ({marks})", (COMMON, *subs))


def search(db: Database, f: fac.Faculty, queries: list[str], k: int = 4) -> tuple[list[Hit], str]:
    """Own content first (library + older notes of this teacher), then the attached Common Library.
    Returns the hits and where they came from ("own" / "common" / "")."""
    legacy = db.all("SELECT id, source_title AS title, text FROM kb_chunks WHERE teacher_id = ? "
                    "AND (faculty_id IS NULL OR faculty_id = ?)", (f.institute_id, f.id))
    own = [(("k", r["id"]), r["title"], None, r["text"]) for r in legacy] + \
          [(("c", r["id"]), r["title"], "library", r["text"]) for r in _own_rows(db, f)]
    hits = bm25(own, queries, k)
    if hits:
        return hits, "own"
    common = [(("c", r["id"]), r["title"], "library", r["text"]) for r in _common_rows(db, f)]
    hits = bm25(common, queries, k)
    return hits, ("common" if hits else "")


def faculty_stats(db: Database, institute: str) -> dict[int, int]:
    """Number of live files each teacher answers from (own library only)."""
    out = {}
    solo = len(fac.list_faculty(db, institute)) == 1
    for f in fac.list_faculty(db, institute, active_only=False):
        if solo and f.active:
            out[f.id] = db.one("SELECT COUNT(*) AS n FROM content_links WHERE owner = ? AND status = 'live'",
                               (institute,))["n"]
            continue
        subs = list(f.subjects) + [fac.GENERAL]
        marks = ",".join("?" * len(subs))
        out[f.id] = db.one(f"SELECT COUNT(*) AS n FROM content_links WHERE owner = ? AND status = 'live' AND "
                           f"(faculty_id = ? OR (faculty_id IS NULL AND subject IN ({marks})))",
                           (institute, f.id, *subs))["n"]
    return out
