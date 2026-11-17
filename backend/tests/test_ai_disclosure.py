"""A7 · "AI Teacher" disclosure: in the app config, on every notes PDF (label, note, watermark, reference)."""
from app.services import notes_pdf


def test_single_note_pdf_says_ai_and_carries_reference():
    h = notes_pdf.build_note_html("Subhash Sir", "Haldighati kab hua?", "1576", [{"title": "Notes"}], "en",
                                  "2026-11-17", "LT-ABCD-EFGH")
    assert 'class="ai">AI Teacher' in h and 'class="wm">AI Teacher' in h
    assert "AI can make mistakes" in h and "Ref LT-ABCD-EFGH" in h


def test_class_notes_pdf_in_hindi_says_ai():
    h = notes_pdf.build_class_notes_html("सुभाष सर", "मुग़ल", [{"heading": "अकबर", "points": ["1556"], "summary": ""}],
                                         "hi", "17 Nov 2026")
    assert "AI टीचर" in h and "AI से गलती हो सकती है" in h and "Ref" not in h


def test_app_config_carries_plain_disclosure(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "d.db"))
    monkeypatch.setenv("LLM_API_KEY", "")
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    main.db.execute("INSERT INTO teachers (id, name, subject) VALUES ('demo', 'Demo Teacher', 'History')")
    j = TestClient(main.app).get("/teacher", headers={"X-Teacher-Id": "demo"}).json()
    assert "AI teacher of Demo Teacher" in j["ai_disclosure"] and "not a real person" in j["ai_disclosure"]
