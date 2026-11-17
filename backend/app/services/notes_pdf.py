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
                    date_text: str, ref: str = "") -> str:
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
  <footer>{esc(t('notes_footer', lang.code, teacher=teacher_name))} · {esc(date_text)}{(' · Ref ' + esc(ref)) if ref else ''}</footer>
</body></html>"""


def build_class_notes_html(teacher_name: str, title: str, sections: list[dict], language: str, date_text: str,
                           ref: str = "") -> str:
    """Whole-class notes: one heading per topic with short points."""
    lang = get_language(language)
    font = SCRIPT_FONTS.get(lang.script, "Noto Sans")
    esc = html.escape
    body = []
    for s in sections:
        body.append(f"<h2>{esc(s['heading'])}</h2><ul>" + "".join(f"<li>{esc(p)}</li>" for p in s["points"]) + "</ul>")
        if s.get("summary"):
            body.append(f"<p class=\"sum\">{esc(s['summary'])}</p>")
    return f"""<!doctype html>
<html lang="{esc(lang.code)}" dir="{'rtl' if lang.rtl else 'ltr'}">
<head><meta charset="utf-8"><title>{esc(title)}</title>
<style>
  @page {{ size: A4; margin: 22mm 18mm; }}
  body {{ font-family: '{font}', 'Noto Sans', sans-serif; color: #111827; font-size: 13pt; line-height: 1.6; }}
  .brand {{ color: #0F766E; font-weight: 700; font-size: 11pt; letter-spacing: .04em; }}
  h1 {{ font-size: 21pt; margin: 6px 0 4px; line-height: 1.3; }}
  .date {{ color: #6B7280; font-size: 10.5pt; margin-bottom: 10px; }}
  h2 {{ font-size: 15pt; margin: 20px 0 6px; color: #0F766E; border-bottom: 1px solid #E5E7EB; padding-bottom: 3px; }}
  ul {{ margin: 0 0 6px; padding-inline-start: 22px; }}
  li {{ margin: 3px 0; }}
  .sum {{ background: #F0FDFA; border-radius: 6px; padding: 6px 10px; font-size: 12pt; }}
  footer {{ margin-top: 28px; border-top: 1px solid #E5E7EB; padding-top: 8px; font-size: 9.5pt; color: #6B7280; }}
</style></head>
<body>
  <div class="brand">{esc(teacher_name)} · {esc(t('notes_title', lang.code))}</div>
  <h1>{esc(title)}</h1>
  <div class="date">{esc(date_text)}</div>
  {''.join(body)}
  <footer>{esc(t('notes_footer', lang.code, teacher=teacher_name))} · {esc(date_text)}{(' · Ref ' + esc(ref)) if ref else ''}</footer>
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
              renderer=None) -> dict:
    """Save one answer from the student's history as a PDF in their library. Saving twice is harmless."""
    existing = db.one("SELECT * FROM saved_notes WHERE student_id = ? AND qa_id = ? AND kind = 'answer'",
                      (student_id, qa_id))
    if existing:
        return dict(existing)
    qa = db.one("SELECT * FROM qa_history WHERE id = ? AND student_id = ?", (qa_id, student_id))
    if qa is None or qa["origin"] == "redirect":   # a "let's study" redirect is not a note
        raise KeyError(qa_id)
    html_text = build_note_html(teacher_name, qa["question"], qa["answer"], json.loads(qa["sources"] or "[]"),
                                qa["language"], qa["created_at"][:10], qa["verify_code"] or "")
    path = os.path.join(notes_dir, str(student_id), f"note_{qa_id}.pdf")
    (renderer or render_pdf)(html_text, path)
    title = qa["question"][:80]
    cur = db.execute("INSERT INTO saved_notes (student_id, qa_id, title, pdf_path) VALUES (?, ?, ?, ?)",
                     (student_id, qa_id, title, path))
    return dict(db.one("SELECT * FROM saved_notes WHERE id = ?", (cur.lastrowid,)))


def _like(q: str | None) -> str:
    return f"%{(q or '').strip()}%"


def list_notes(db: Database, student_id: int, offset: int = 0, limit: int = 20, q: str | None = None) -> dict:
    """One page of saved notes, newest first, optionally filtered by a search word."""
    limit = max(1, min(limit, 100))
    where, args = "student_id = ? AND title LIKE ?", (student_id, _like(q))
    total = db.one(f"SELECT COUNT(*) AS n FROM saved_notes WHERE {where}", args)["n"]
    rows = db.all(f"SELECT id, qa_id, title, created_at, kind, topics FROM saved_notes WHERE {where} "
                  "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", (*args, limit, max(offset, 0)))
    items = []
    for r in rows:
        item = dict(r)
        item["topics"] = json.loads(item["topics"] or "[]")
        items.append(item)
    return {"items": items, "total": total}


def list_history(db: Database, student_id: int, offset: int = 0, limit: int = 30, q: str | None = None) -> dict:
    """One page of the question history, newest first, with a 'pdf_saved' flag per answer."""
    limit = max(1, min(limit, 100))
    where = "q.student_id = ? AND (q.question LIKE ? OR q.answer LIKE ?)"
    args = (student_id, _like(q), _like(q))
    total = db.one(f"SELECT COUNT(*) AS n FROM qa_history q WHERE {where}", args)["n"]
    # saved on its own, or inside the notes of its class (class notes leave out redirects and small talk)
    rows = db.all(f"SELECT q.*, EXISTS (SELECT 1 FROM saved_notes n WHERE n.student_id = q.student_id AND "
                  f"((n.kind = 'answer' AND n.qa_id = q.id) OR (n.kind = 'class' AND n.session_id = q.session_id "
                  f"AND q.origin != 'redirect' AND COALESCE(q.notes_worthy, 1) = 1))) AS pdf_saved FROM qa_history q "
                  f"WHERE {where} ORDER BY q.id DESC LIMIT ? OFFSET ?", (*args, limit, max(offset, 0)))
    items = []
    for r in rows:
        item = dict(r)
        item["sources"] = json.loads(item["sources"] or "[]")
        item["pdf_saved"] = bool(item["pdf_saved"])
        items.append(item)
    return {"items": items, "total": total}


def library(db: Database, student_id: int, q: str | None = None, notes_preview: int = 10,
            history_offset: int = 0, history_limit: int = 30) -> dict:
    """My Library screen: the latest few saved notes (the rest via list_notes) and one page of history.
    Works the same with 5 notes or 5,000 — the app never loads everything at once."""
    notes = list_notes(db, student_id, 0, notes_preview, q)
    history = list_history(db, student_id, history_offset, history_limit, q)
    return {"saved_notes": notes["items"], "notes_total": notes["total"],
            "history": history["items"], "history_total": history["total"]}
