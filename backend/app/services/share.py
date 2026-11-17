"""Share links. Everything a student shares (the app, notes PDF, a test score) carries one link:
<PUBLIC_BASE_URL>/t/<teacher id>. That page shows the teacher and a "Get the app" button that goes to the teacher's
Play Store listing (set in Admin → teacher → Play Store link). The link never changes, even if the store link does.
"""
import html
import re

_PLAY = re.compile(r"^https://play\.google\.com/store/apps/details\?id=[A-Za-z0-9_.]+(&[A-Za-z0-9_=.&-]*)?$")


def share_url(public_base_url: str, teacher_id: str, request_base: str = "") -> str:
    base = (public_base_url or request_base or "").rstrip("/")
    return f"{base}/t/{teacher_id}"


def clean_play_store_url(value: str | None) -> str:
    """Only a real Play Store link (or a bare package id) is accepted, so the share page can't send people elsewhere."""
    v = (value or "").strip()
    if not v:
        return ""
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+", v):
        v = f"https://play.google.com/store/apps/details?id={v}"
    if not _PLAY.match(v):
        raise ValueError("Play Store link must look like https://play.google.com/store/apps/details?id=com.example.app")
    return v


def share_page_html(teacher: dict) -> str:
    esc = html.escape
    name = teacher.get("name") or ""
    app_name = teacher.get("app_name") or f"{name} AI"
    subject = teacher.get("subject") or ""
    color = teacher.get("brand_color") or "#2DD4BF"
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        color = "#2DD4BF"
    photo = teacher.get("avatar_url") or ""
    photo = photo if photo.startswith("https://") else ""
    store = teacher.get("play_store_url") or ""
    button = (f'<a class="btn" href="{esc(store)}" rel="noopener">Get the app on Google Play</a>' if store
              else '<p class="soon">The app is coming to Google Play soon.</p>')
    img = f'<img src="{esc(photo)}" alt="{esc(name)}">' if photo else ""
    desc = f"Learn {subject} with {name}'s AI teacher — ask in Hindi, English, Punjabi or any language."
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(app_name)}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(app_name)}">
<meta property="og:description" content="{esc(desc)}">
{f'<meta property="og:image" content="{esc(photo)}">' if photo else ''}
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https:; style-src 'unsafe-inline'">
<style>
  body {{ margin: 0; font-family: system-ui, 'Noto Sans', sans-serif; background: #F8FAFC; color: #0F172A;
         display: flex; min-height: 100vh; align-items: center; justify-content: center; }}
  .card {{ background: #fff; border-radius: 24px; padding: 32px 26px; max-width: 380px; width: 88%;
          text-align: center; box-shadow: 0 10px 30px rgba(15,23,42,.08); }}
  img {{ width: 120px; height: 120px; border-radius: 50%; object-fit: cover; border: 4px solid {color}; }}
  h1 {{ font-size: 24px; margin: 16px 0 4px; }}
  .sub {{ color: #475569; margin: 0 0 18px; line-height: 1.5; }}
  .btn {{ display: inline-block; background: {color}; color: #0F172A; font-weight: 800; padding: 14px 22px;
         border-radius: 999px; text-decoration: none; }}
  .soon {{ color: #475569; font-weight: 600; }}
  small {{ display: block; margin-top: 22px; color: #94A3B8; }}
</style></head>
<body><main class="card">
  {img}
  <h1>{esc(app_name)}</h1>
  <p class="sub">{esc(desc)}</p>
  {button}
  <small>LiveTeach · AI teacher</small>
</main></body></html>"""
