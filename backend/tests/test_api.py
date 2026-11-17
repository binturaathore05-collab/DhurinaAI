"""End-to-end check of the HTTP API: login with OTP, ask, save a note, library, demo limit."""
import importlib
import os
import re

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Teacher', 'History')")
    sent = []
    main.otp.sms_sender = lambda phone, msg: sent.append(msg)
    def fake_render(html, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(b"%PDF")
    monkeypatch.setattr(main.notes_pdf, "render_pdf", fake_render)
    c = TestClient(main.app)
    c.headers["X-Teacher-Id"] = "demo"
    c.sent = sent
    return c


def login(c):
    assert c.post("/auth/otp", json={"phone": "9876543210"}).status_code == 200
    code = re.search(r"\d{6}", c.sent[-1]).group()
    r = c.post("/auth/verify", json={"phone": "9876543210", "code": code})
    assert r.status_code == 200 and r.json()["demo_questions_left"] == 3
    c.headers["Authorization"] = "Bearer " + r.json()["token"]


def test_full_flow(client):
    assert client.get("/teacher").json()["name"] == "Demo Teacher"
    login(client)
    r = client.post("/class/ask", json={"question": "Who was Akbar?"}).json()
    assert r["type"] == "answer" and r["demo_questions_left"] == 2
    saved = client.post("/class/ask", json={"question": "Sir, save this", "last_qa_id": r["qa_id"]}).json()
    assert saved["type"] == "note_saved"
    lib = client.get("/library").json()
    # "save this" now saves the notes of the whole class so far (one PDF per class)
    assert lib["saved_notes"][0]["kind"] == "class" and lib["history"][0]["pdf_saved"]
    assert saved["note"]["id"] == lib["saved_notes"][0]["id"]
    client.post("/class/ask", json={"question": "Q2"})
    client.post("/class/ask", json={"question": "Q3"})
    over = client.post("/class/ask", json={"question": "Q4"})
    assert over.status_code == 402 and "Subscribe" in over.json()["detail"]
    assert client.get("/me/access").json()["state"] == "demo"


def test_wrong_otp_and_no_token(client):
    client.post("/auth/otp", json={"phone": "9876543210"})
    assert client.post("/auth/verify", json={"phone": "9876543210", "code": "999999x"}).status_code == 400
    assert client.get("/library").status_code == 422  # no Authorization header


def test_class_notes_test_series_and_share_over_http(client):
    import app.main as main
    login(client)
    t = client.get("/teacher").json()
    assert t["share_url"].endswith("/t/demo")
    page = client.get("/t/demo")
    assert page.status_code == 200 and "Demo Teacher" in page.text and "coming to Google Play soon" in page.text
    assert client.get("/t/nobody").status_code == 404

    offer = client.post("/class/ask", json={"question": "Sir test lo"}).json()
    assert offer["type"] == "test_offer" and not offer["can_test"]       # nothing studied yet
    client.post("/class/ask", json={"question": "Who was Akbar?"})
    cur = client.get("/class/current").json()
    assert cur["can_test"] and cur["topics"]

    main.llm.replies = [{"questions": [{"q": f"Q{i}", "options": ["r", "w1", "w2", "w3"], "answer": 0,
                                        "explain": "", "topic": "Akbar"} for i in range(10)]}]
    test = client.post("/tests", json={"mode": "mcq"}).json()
    assert test["total"] == 10 and "answer" not in test["question"]
    assert client.get("/me/access").json()["demo_questions_left"] == 1   # a test counts as one question
    r = client.post(f"/tests/{test['id']}/answer", json={"answer": "A"})
    assert r.status_code == 200 and r.json()["test"]["index"] == 1
    assert client.post("/tests", json={"mode": "essay"}).status_code == 400

    note = client.post("/class/notes", json={}).json()
    assert note["kind"] == "class"
    ended = client.post("/class/end").json()
    assert ended["can_test"] and ended["notes_id"] == note["id"]
    assert client.get("/class/current").json()["session_id"] is None
    assert client.post("/class/notes", json={"session_id": 9999}).status_code == 404
