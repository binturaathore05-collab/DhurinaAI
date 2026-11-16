"""Turn a saved answer into a PDF note, in the student's language and script.

PDFs are rendered from HTML by headless Chromium (Playwright), because Indian scripts need proper
text shaping (conjuncts, matras) that simple PDF libraries get wrong. Install Noto fonts on the server
(`fonts-noto` on Debian/Ubuntu) so every script renders.
"""
import html
import json
import os

from ..db import Database
from ..i18n import t
from ..languages import SCRIPT_FONTS, get_language


def build_note_html(teacher_name: str, question: str, answer: str, sources: list[dict], language: str,
                    date_text: str) -> str:
    lang = get_language(language)
    font = SCRIPT_FONTS.get(lang.script, "Noto Sans")
    esc = html.escape
    paras = "".join(f"<p>{esc(p)}</p>" for p in answer.split("\n") if p.strip())
    src = " · ".join(esc(s.get("title", "")) for s in sources)
    return f"""<!doctype html>
<html lang="{esc(lang.code)}" dir="{'rtl' if lang.rtl else 'ltr'}">
<head><meta charset="utf-8"><title>{esc(question)}</title>
<style>
  @page {{ size: A4; margin: 22mm 18mm; }}
  body {{ font-family: '{font}', 'Noto Sans', sans-serif; color: #111827; font-size: 13pt; line-height: 1.6; }}
  .brand {{ color: #0F766E; font-weight: 700; font-size: 11pt; letter-spacing: .04em; }}
  h1 {{ font-size: 20pt; margin: 6px 0 14px; line-height: 1.3; }}
  .label {{ font-size: 10pt; color: #4B5563; text-transform: uppercase; letter-spacing: .06em; }}
  .src {{ margin-top: 18px; font-size: 10.5pt; color: #0F766E; }}
  footer {{ margin-top: 28px; border-top: 1px solid #E5E7EB; padding-top: 8px; font-size: 9.5pt; color: #6B7280; }}
</style></head>
<body>
  <div class="brand">{esc(teacher_name)} · {esc(t('notes_title', lang.code))}</div>
  <div class="label">{esc(t('notes_question', lang.code))}</div>
  <h1>{esc(question)}</h1>
  {paras}
  <div class="src">{esc(t('notes_source', lang.code))}: {src}</div>
  <footer>{esc(t('notes_footer', lang.code, teacher=teacher_name))} · {esc(date_text)}</footer>
</body></html>"""


def render_pdf(html_text: str, out_path: str, chromium_path: str | None = None) -> str:
    from playwright.sync_api import sync_playwright  # imported lazily: only the notes worker needs it

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium_path) if chromium_path else p.chromium.launch()
        page = browser.new_page()
        page.set_content(html_text, wait_until="load")
        page.pdf(path=out_path, format="A4", print_background=True)
        browser.close()
    return out_path


def save_note(db: Database, student_id: int, qa_id: int, teacher_name: str, notes_dir: str,
              renderer=render_pdf) -> dict:
    """Save one answer from the student's history as a PDF in their library. Saving twice is harmless."""
    existing = db.one("SELECT * FROM saved_notes WHERE student_id = ? AND qa_id = ?", (student_id, qa_id))
    if existing:
        return dict(existing)
    qa = db.one("SELECT * FROM qa_history WHERE id = ? AND student_id = ?", (qa_id, student_id))
    if qa is None:
        raise KeyError(qa_id)
    html_text = build_note_html(teacher_name, qa["question"], qa["answer"], json.loads(qa["sources"] or "[]"),
                                qa["language"], qa["created_at"][:10])
    path = os.path.join(notes_dir, str(student_id), f"note_{qa_id}.pdf")
    renderer(html_text, path)
    title = qa["question"][:80]
    cur = db.execute("INSERT INTO saved_notes (student_id, qa_id, title, pdf_path) VALUES (?, ?, ?, ?)",
                     (student_id, qa_id, title, path))
    return dict(db.one("SELECT * FROM saved_notes WHERE id = ?", (cur.lastrowid,)))


def library(db: Database, student_id: int) -> dict:
    """Everything for the My Library screen: saved notes and question history (newest first)."""
    notes = [dict(r) for r in db.all("SELECT id, qa_id, title, created_at FROM saved_notes "
                                     "WHERE student_id = ? ORDER BY id DESC", (student_id,))]
    saved_ids = {n["qa_id"] for n in notes}
    history = []
    for r in db.all("SELECT * FROM qa_history WHERE student_id = ? ORDER BY id DESC", (student_id,)):
        item = dict(r)
        item["sources"] = json.loads(item["sources"] or "[]")
        item["pdf_saved"] = r["id"] in saved_ids
        history.append(item)
    return {"saved_notes": notes, "history": history}
