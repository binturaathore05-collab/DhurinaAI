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
    assert lib["saved_notes"][0]["qa_id"] == r["qa_id"] and lib["history"][0]["pdf_saved"]
    client.post("/class/ask", json={"question": "Q2"})
    client.post("/class/ask", json={"question": "Q3"})
    over = client.post("/class/ask", json={"question": "Q4"})
    assert over.status_code == 402 and "Subscribe" in over.json()["detail"]


def test_wrong_otp_and_no_token(client):
    client.post("/auth/otp", json={"phone": "9876543210"})
    assert client.post("/auth/verify", json={"phone": "9876543210", "code": "999999x"}).status_code == 400
    assert client.get("/library").status_code == 422  # no Authorization header
