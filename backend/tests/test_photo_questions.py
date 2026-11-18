"""Phase C: photo questions (safety check of the photo, read the question, normal path) and the one-time AI intro."""
import base64
import importlib
import io
import re

import pytest

pytest.importorskip("fastapi")
PIL = pytest.importorskip("PIL")
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402


def _jpeg(size=(1600, 1200), exif=False) -> str:
    img = Image.new("RGB", size, (240, 240, 230))
    out = io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "PhoneMaker"   # camera make; real phones also add GPS here
        img.save(out, "JPEG", exif=ex.tobytes())
    else:
        img.save(out, "JPEG")
    return base64.b64encode(out.getvalue()).decode()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ph.db"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name) VALUES ('demo', 'Demo Sir')")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append((phone, msg))
    c = TestClient(main.app)
    c.headers["X-Teacher-Id"] = "demo"
    c.post("/auth/otp", json={"phone": "9876500001"})
    tok = c.post("/auth/verify", json={"phone": "9876500001", "code": re.search(r"\d{6}", sent[-1][1]).group()}).json()["token"]
    c.headers["Authorization"] = "Bearer " + tok
    fake = main.raw_llm.pick()
    return c, main, fake


def test_photo_question_is_read_then_answered(setup):
    c, main, fake = setup
    fake.replies = [{"safe": True, "category": "none", "question": "प्रकाश संश्लेषण क्या है?"}]
    r = c.post("/class/ask-photo", json={"photo_base64": _jpeg(), "caption": "Q1 samjhao"})
    j = r.json()
    assert r.status_code == 200 and j["type"] == "answer" and j["photo_text"] == "प्रकाश संश्लेषण क्या है?"
    assert j["answer"]
    row = main.db.one("SELECT question FROM qa_history ORDER BY id DESC LIMIT 1")
    assert row["question"].startswith("प्रकाश संश्लेषण क्या है?")   # the read question is kept, the photo is not
    assert "Student's note: Q1 samjhao" in fake.calls[0][1]


def test_unsafe_photo_never_reaches_the_teacher(setup):
    c, main, fake = setup
    fake.replies = [{"safe": False, "category": "sexual", "question": "x"}]
    j = c.post("/class/ask-photo", json={"photo_base64": _jpeg()}).json()
    assert j["type"] == "answer" and j["scope"] == "unsafe" and j["photo_text"] == ""
    assert len(fake.calls) == 1   # only the reading call; no answer was written by the AI
    ev = main.db.one("SELECT stage, category, severity, action, excerpt FROM safety_events ORDER BY id DESC LIMIT 1")
    assert (ev["stage"], ev["category"], ev["action"]) == ("input", "sexual", "refused") and ev["excerpt"].startswith("[photo]")


def test_unreadable_photo_asks_again_and_costs_no_question(setup):
    c, main, fake = setup
    fake.replies = [{"safe": True, "category": "none", "question": ""}]
    before = c.get("/me/access").json()["demo_questions_left"]
    j = c.post("/class/ask-photo", json={"photo_base64": _jpeg()}).json()
    assert j["type"] == "photo_unclear" and "फ़ोटो" in j["message"]
    assert c.get("/me/access").json()["demo_questions_left"] == before


def test_photo_switch_and_bad_files(setup):
    c, main, fake = setup
    assert c.post("/class/ask-photo", json={"photo_base64": base64.b64encode(b"%PDF-1.4 not a photo").decode()}).status_code == 400
    main.switches.set_switch(main.db, "photo", True, "testing", "owner")
    r = c.post("/class/ask-photo", json={"photo_base64": _jpeg()})
    assert r.status_code == 503 and "switched off" in r.json()["detail"]


def test_photo_is_cleaned_and_made_smaller():
    from app.services import photo
    out = photo.prepare(base64.b64decode(_jpeg((3000, 2000), exif=True)))
    img = Image.open(io.BytesIO(out))
    assert max(img.size) == photo.MAX_SIDE and not img.getexif()   # no camera / GPS data left


def test_photo_limit_per_day(setup):
    c, main, fake = setup
    main.admin.save_settings(main.db, {**main.admin.get_settings(main.db), "limits": {"photos_per_day": 1}}) \
        if hasattr(main.admin, "save_settings") else pytest.skip("no settings saver")
    c.post("/class/ask-photo", json={"photo_base64": _jpeg()})
    r = c.post("/class/ask-photo", json={"photo_base64": _jpeg()})
    assert r.status_code == 429


def test_saying_photo_opens_the_camera(setup):
    c, main, fake = setup
    assert c.post("/class/ask", json={"question": "Sir photo se puchna hai"}).json()["type"] == "photo"
    assert c.post("/class/ask", json={"question": "फोटो भेजना है"}).json()["type"] == "photo"


def test_ai_intro_only_before_the_first_question(setup):
    c, main, fake = setup
    intro = c.get("/me/access").json()["ai_intro"]
    assert "AI teacher" in intro["en"] and "Demo Sir" in intro["en"] and "AI टीचर" in intro["hi"]
    c.post("/class/ask", json={"question": "What is photosynthesis?"})
    assert c.get("/me/access").json()["ai_intro"] is None
