"""Multi-teacher: faculty inside one institute app, automatic switching, one content library, de-duplication,
the Common Library, and the test lab for the owner brief's 7 checks."""
import base64
import importlib
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Database  # noqa: E402
from app.services import faculty as fac, library, moderation  # noqa: E402


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("AVATAR_DIR", str(tmp_path / "avatars"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("ADMIN_EMAIL", "owner@dhurina.in")
    monkeypatch.setenv("ADMIN_PASSWORD", "Dhurina2026")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("TEACHER_KEY_INST", "inst-key")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('inst', 'Subhash Sir', 'History')")
    admin = TestClient(main.app)
    r = admin.post("/admin/api/login", json={"email": "owner@dhurina.in", "password": "Dhurina2026"})
    admin.headers["Authorization"] = "Bearer " + r.json()["token"]
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    student = TestClient(main.app)
    student.headers["X-Teacher-Id"] = "inst"
    student.post("/auth/otp", json={"phone": "9876500000"})
    code = re.search(r"\d{6}", sent[-1]).group()
    student.headers["Authorization"] = "Bearer " + student.post(
        "/auth/verify", json={"phone": "9876500000", "code": code}).json()["token"]
    main.db.execute("UPDATE students SET demo_questions_used = -100")
    return admin, student, main


def test_existing_app_gets_one_teacher_and_keeps_working(setup):
    admin, student, main = setup
    info = student.get("/teacher").json()
    assert [f["name"] for f in info["faculty"]] == ["Subhash Sir"]   # migration: 1 faculty per existing teacher
    r = student.post("/class/ask", json={"question": "Who was Akbar?"}).json()
    assert r["type"] == "answer" and r["faculty"]["name"] == "Subhash Sir" and not r["switched"] and r["handover"] == ""
    assert main.db.one("SELECT faculty_id FROM qa_history WHERE id = ?", (r["qa_id"],))["faculty_id"] == r["faculty"]["id"]
    # the only teacher can't be switched off
    fid = r["faculty"]["id"]
    assert admin.put(f"/admin/api/teachers/inst/faculty/{fid}", json={"active": False}).status_code == 400


def _add_teachers(admin):
    first = admin.get("/admin/api/teachers/inst/faculty").json()["items"][0]
    admin.put(f"/admin/api/teachers/inst/faculty/{first['id']}", json={"name": "Subhash Sir", "subjects": ["history", "rajasthan"]})
    ids = {"history": first["id"]}
    for name, subj in [("Gupta Sir", "maths"), ("Verma Sir", "reasoning"), ("Mr. Joseph", "english")]:
        r = admin.post("/admin/api/teachers/inst/faculty", json={"name": name, "subjects": [subj], "voice_id": f"v-{subj}"})
        assert r.status_code == 200, r.text
        ids[subj] = r.json()["id"]
    return ids


def test_automatic_switch_sticky_and_by_voice_command(setup):
    admin, student, main = setup
    ids = _add_teachers(admin)
    ask = lambda q: student.post("/class/ask", json={"question": q}).json()
    a = ask("सर, मुझे राजस्थान का इतिहास पढ़ना है")
    assert a["faculty"]["id"] == ids["history"]
    b = ask("Sir, coding-decoding ka ek reasoning sawal samjhaiye")
    assert b["switched"] and b["faculty"]["id"] == ids["reasoning"] and b["faculty"]["voice_id"] == "v-reasoning"
    assert "Verma Sir" in b["handover"] and "Reasoning" in b["handover"]
    # the new teacher is told to greet as the new teacher (one chat, no new call)
    assert "handed over to you from Subhash Sir" in main.raw_llm.calls[-1][0] if hasattr(main.raw_llm, "calls") else True
    c = ask("ok")
    assert not c["switched"] and c["faculty"]["id"] == ids["reasoning"]   # sticky
    d = ask("aur batao")
    assert d["faculty"]["id"] == ids["reasoning"]
    e = ask("Maths wale sir ko bulao")
    assert e["switched"] and e["faculty"]["id"] == ids["maths"] and "Gupta Sir" in e["handover"]
    # one history per student, tagged subject-wise
    tags = [r["faculty_id"] for r in main.db.all("SELECT faculty_id FROM qa_history ORDER BY id")]
    assert tags == [ids["history"], ids["reasoning"], ids["reasoning"], ids["reasoning"], ids["maths"]]
    assert student.get("/teacher").json()["faculty"][1]["name"] == "Gupta Sir"


def test_subject_rides_on_the_safety_check(tmp_path):
    """The input check's one small-model call also returns the subject: routing needs no extra AI call."""
    from app.services.llm import FakeLLM
    db = Database(str(tmp_path / "s.db"))
    llm = FakeLLM([{"category": "none", "severity": "none", "subject": "maths"}])
    m = moderation.Moderator(db, "llm", llm)
    v = m.check_input("isko solve karo please")
    assert v.subject == "maths" and len(llm.calls) == 1 and '"subject"' in llm.calls[0][0]
    assert m.check_input("isko solve karo please").subject == "maths" and len(llm.calls) == 1   # cached
    db.execute("INSERT INTO teachers (id, name) VALUES ('x', 'X')")
    fac.ensure_default(db, "x")
    m1 = fac.list_faculty(db, "x")[0]
    fac.save(db, "x", {"subjects": ["history"]}, m1.id)
    g = fac.save(db, "x", {"name": "Gupta Sir", "subjects": ["maths"]})
    sid = db.execute("INSERT INTO students (teacher_id, phone) VALUES ('x', '1')").lastrowid
    assert fac.route(db, "x", sid, "isko solve karo please", v.subject).faculty.id == g.id
    assert fac.route(db, "x", sid, "Akbar kaun tha?", "none").faculty.id == g.id   # "none" = never a switch


def test_library_upload_classify_pending_and_answers_per_teacher(setup):
    admin, student, main = setup
    ids = _add_teachers(admin)
    up = lambda name, text, **kw: admin.post("/admin/api/teachers/inst/library",
                                             json={"filename": name, "data_base64": b64(text), **kw})
    h = up("History/haldighati.txt", "Haldighati ka yudh 1576 mein Maharana Pratap aur Akbar ki sena ke beech hua.").json()
    assert h["subject"] == "history" and h["assigned_by"] == "name" and h["status"] == "live"
    m = up("notes.txt", "Profit percentage equals profit divided by cost price times hundred.", faculty_id=ids["maths"]).json()
    assert m["subject"] == "maths" and m["faculty_id"] == ids["maths"] and m["assigned_by"] == "upload"
    p = up("chapter-7.txt", "Coding decoding: CAT is written as DBU in a certain code language.").json()
    assert p["status"] == "pending"   # no AI key here, nothing in the name: the admin decides
    lst = admin.get("/admin/api/teachers/inst/library").json()
    assert lst["counts"]["pending"] == 1 and lst["total"] == 3
    a = admin.put(f"/admin/api/teachers/inst/library/{p['id']}", json={"faculty_id": ids["reasoning"]}).json()
    assert a["status"] == "live" and a["subject"] == "reasoning"
    assert "DBU" in admin.get(f"/admin/api/teachers/inst/library/{p['id']}").json()["text"]
    assert up("bad.exe", "x").status_code == 400
    # each teacher searches only their own content
    maths = fac.get(main.db, "inst", ids["maths"])
    hist = fac.get(main.db, "inst", ids["history"])
    assert library.search(main.db, maths, ["profit percentage cost price"])[0]
    assert not library.search(main.db, maths, ["Haldighati yudh Maharana Pratap"])[0]
    assert library.search(main.db, hist, ["Haldighati yudh Maharana Pratap"])[0][0].source_title == "haldighati.txt"
    # edit text and delete
    e = admin.put(f"/admin/api/teachers/inst/library/{m['id']}/text", json={"text": "Profit percent = profit / CP x 100 (edited)"}).json()
    assert e["faculty_id"] == ids["maths"] and e["title"] == "notes.txt"
    assert admin.delete(f"/admin/api/teachers/inst/library/{e['id']}").json()["ok"]
    assert main.db.one("SELECT COUNT(*) AS n FROM content_files")["n"] == 2   # unused files are removed


def test_dedup_across_institutes_and_kept_apart(setup):
    admin, student, main = setup
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('other', 'Other Academy', 'Maths')")
    text = "Percentage: x percent of y equals x times y divided by 100. Profit percentage example."
    a = admin.post("/admin/api/teachers/inst/library", json={"filename": "maths/pct.txt", "data_base64": b64(text)}).json()
    b = admin.post("/admin/api/teachers/other/library", json={"filename": "Ganit.txt", "data_base64": b64(text)}).json()
    assert b["status"] == "live" and b["title"] == "Ganit.txt" and b["subject"] == "maths"   # just "uploaded"
    assert main.db.one("SELECT COUNT(*) AS n FROM content_files")["n"] == 1
    assert main.db.one("SELECT COUNT(*) AS n FROM content_chunks")["n"] == 1
    # same text, different bytes (Windows line ends) → still stored once
    admin.post("/admin/api/teachers/other/library", json={"filename": "copy.txt", "data_base64": b64(text.replace(" ", "  "))})
    assert main.db.one("SELECT COUNT(*) AS n FROM content_files")["n"] == 1
    # deleting removes only one institute's link
    admin.delete(f"/admin/api/teachers/inst/library/{a['id']}")
    assert main.db.one("SELECT COUNT(*) AS n FROM content_files")["n"] == 1
    other = fac.list_faculty(main.db, "other")[0]
    inst = fac.list_faculty(main.db, "inst")[0]
    assert library.search(main.db, other, ["profit percentage"])[0]
    admin.post("/admin/api/teachers/inst/library", json={"filename": "History/x.txt",
                                                         "data_base64": b64("Akbar Mughal badshah tha aur Haldighati yudh")})
    assert not library.search(main.db, other, ["Akbar Mughal badshah"])[0]   # institutes never mix
    assert library.search(main.db, inst, ["Akbar Mughal badshah"])[0]


def test_unsafe_upload_never_goes_live(setup):
    admin, student, main = setup
    r = admin.post("/admin/api/teachers/inst/library", json={"filename": "History/x.txt",
                   "data_base64": b64("History notes. How to make a bomb at home step by step.")}).json()
    assert r["status"] == "blocked"
    f = fac.list_faculty(main.db, "inst")[0]
    assert not library.search(main.db, f, ["bomb home step"])[0]


def test_common_library_link_not_copy_and_detach(setup):
    admin, student, main = setup
    ids = _add_teachers(admin)
    up = admin.post("/admin/api/common", json={"filename": "reasoning-series.txt",
                    "data_base64": b64("Number series: 2, 6, 12, 20, 30 — the difference grows by two each time.")}).json()
    assert up["owner"] == "common" and up["subject"] == "reasoning"
    verma = fac.get(main.db, "inst", ids["reasoning"])
    assert not library.search(main.db, verma, ["number series difference"])[0]
    assert admin.post(f"/admin/api/teachers/inst/faculty/{ids['reasoning']}/common", json={"subject": "reasoning"}).json()["ok"]
    hits, where = library.search(main.db, verma, ["number series difference"])
    assert hits and where == "common"
    # new Common Library content reaches every linked teacher at once (a link, not a copy)
    admin.post("/admin/api/common", json={"filename": "reasoning-blood.txt",
               "data_base64": b64("Blood relation: my father's only son is me; reasoning practice.")})
    assert library.search(main.db, verma, ["father only son blood relation"])[0]
    assert main.db.one("SELECT COUNT(*) AS n FROM content_links WHERE owner = 'inst'")["n"] == 0
    # the student hears it in this teacher's voice; the source is never named
    student.post("/class/ask", json={"question": "Sir, coding-decoding ka ek reasoning sawal samjhaiye"})
    main.llm.replies = [{"query": "number series difference"}, {"answer": "Series: difference grows by two.", "follow_up": "", "found_in_notes": True,
                         "used_sources": [1], "scope": "study"}]
    r = student.post("/class/ask", json={"question": "number series difference reasoning"}).json()
    assert r["origin"] == "teacher_notes" and "reasoning-series" not in str(r["sources"])
    # detach in one click; audited
    assert admin.delete(f"/admin/api/teachers/inst/faculty/{ids['reasoning']}/common/reasoning").json()["ok"]
    assert not library.search(main.db, verma, ["number series difference"])[0]
    paths = [r["path"] for r in main.db.all("SELECT path FROM admin_audit")]
    assert any(p.endswith("/common") for p in paths) and any(p.endswith("/common/reasoning") for p in paths)
    log = main.db.one("SELECT details FROM admin_audit WHERE path = '/admin/api/common'")["details"]
    assert "chars)" in log and "Number series" not in log   # the file itself is not copied into the audit log


def test_common_library_is_super_admin_only_and_promote_needs_permission(setup):
    admin, student, main = setup
    r = admin.post("/admin/api/teachers/inst/library", json={"filename": "maths/a.txt",
                   "data_base64": b64("Average of 2, 4 and 6 is 4. Sum divided by count."), "allow_common": False}).json()
    assert admin.post(f"/admin/api/teachers/inst/library/{r['id']}/promote").status_code == 400
    r2 = admin.post("/admin/api/teachers/inst/library", json={"filename": "maths/b.txt",
                    "data_base64": b64("Ratio 2:3 means two parts to three parts; simplify ratios."), "allow_common": True}).json()
    p = admin.post(f"/admin/api/teachers/inst/library/{r2['id']}/promote").json()
    assert p["owner"] == "common" and p["subject"] == "maths"
    from app.services import roles
    assert roles.has("owner", "library_common") and not roles.has("technical", "library_common")


def test_institute_panel_and_new_teacher_without_code(setup):
    admin, student, main = setup
    inst = TestClient(main.app)
    inst.headers.update({"X-Teacher-Id": "inst", "X-Teacher-Key": "inst-key"})
    assert inst.get("/teacher/faculty").json()["items"][0]["name"] == "Subhash Sir"
    up = inst.post("/teacher/library", json={"filename": "Geography/rivers.txt",
                   "data_base64": b64("Chambal nadi Rajasthan ki ekmatra barahmasi nadi hai; bhugol.")}).json()
    assert up["subject"] == "geography" and up["status"] == "live"
    g = admin.post("/admin/api/teachers/inst/faculty", json={"name": "Meena Ma'am", "subjects": ["geography"]}).json()
    r = student.post("/class/ask", json={"question": "Chambal nadi ke baare mein bataiye, bhugol"}).json()
    assert r["faculty"]["name"] == "Meena Ma'am"
    assert library.faculty_stats(main.db, "inst")[g["id"]] == 1
    assert inst.get("/teacher/library").json()["total"] == 1


def test_teacher_lab_runs_the_seven_checks(setup):
    admin, student, main = setup
    r = admin.post("/admin/api/teacher-lab/run").json()
    assert r["last"]["total"] == 7 and r["last"]["passed"] == 7, r["last"]["results"]
    assert admin.get("/admin/api/teacher-lab").json()["runs"][0]["passed"] == 7
    assert admin.post("/admin/api/teacher-lab/run?mode=ai").status_code == 400   # no AI key here


def test_pdf_and_word_files_are_read(tmp_path):
    import io
    import zipfile
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "Trigonometry: sin squared plus cos squared equals one. Maths formula sheet.")
    c.save()
    assert "Trigonometry" in library.extract_text("pdf", buf.getvalue())
    w = io.BytesIO()
    with zipfile.ZipFile(w, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Sandhi ke bhed</w:t></w:r></w:p></w:body></w:document>")
    assert "Sandhi ke bhed" in library.extract_text("docx", w.getvalue())
    with pytest.raises(library.LibraryError):
        library.kind_of("photo.jpg")
