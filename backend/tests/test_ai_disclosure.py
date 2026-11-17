"""A7 (owner, 17 Nov 2026): no "AI" labels during class or on notes — disclosure is at app start and in the policy.
Notes PDFs still carry the answer's reference code (A5) so a shared PDF can be checked."""
from app.services import notes_pdf


def test_note_pdf_has_no_ai_label_but_keeps_reference():
    h = notes_pdf.build_note_html("Subhash Sir", "Haldighati kab hua?", "1576", [{"title": "Notes"}], "en",
                                  "2026-11-17", "LT-ABCD-EFGH")
    assert "AI Teacher" not in h and "AI can make mistakes" not in h and 'class="wm"' not in h
    assert "Ref LT-ABCD-EFGH" in h


def test_class_notes_pdf_has_no_ai_label():
    h = notes_pdf.build_class_notes_html("सुभाष सर", "मुग़ल", [{"heading": "अकबर", "points": ["1556"], "summary": ""}],
                                         "hi", "17 Nov 2026")
    assert "AI टीचर" not in h and "Ref" not in h
