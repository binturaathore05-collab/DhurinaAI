"""Phase C · Photo questions. The student takes a photo of a book page / notebook / diagram and asks Sir.

Steps (nothing unchecked reaches the AI teacher or the student):
  1. prepare  – only a real JPEG / PNG / WebP photo, at most 8 MB; turned upright, made smaller (long side 1280 px)
                and saved again as a plain JPEG, so location data (EXIF / GPS) and anything hidden in the file are gone.
  2. check    – the photo's safety check before anything reads it: OpenAI's free image check when OpenAI is the
                checker; otherwise the reading model's own safety answer (step 3) is the check.
  3. read     – one call to the AI model that can see photos: it copies the question from the photo (same language
                and script), or says it can't read it. It never answers.
  4. the read question then goes through the normal path: text safety check → teacher → answer → answer check.

The photo itself is never stored (only the question that was read from it), to keep children's photos off our servers.
"""
import base64
import io
import json
import urllib.request
from dataclasses import dataclass

from .moderation import OPENAI_MAP, Unavailable, Verdict

MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE = 1280            # enough to read a textbook page; keeps the AI cost of one photo low
MAX_PIXELS = 40_000_000    # refuse "decompression bomb" files
FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}


class PhotoError(ValueError):
    """A message ready for the student."""


def prepare(data: bytes) -> bytes:
    from PIL import Image, ImageOps
    if not data:
        raise PhotoError("No photo was received. Please try again.")
    if len(data) > MAX_BYTES:
        raise PhotoError("This photo is too big. Please take it again.")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in FORMATS:
            raise PhotoError("Please send a photo (JPG or PNG).")
        img.load()
        img = ImageOps.exif_transpose(img)
    except PhotoError:
        raise
    except Exception:
        raise PhotoError("Sir couldn't open this photo. Please take it again.")
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80, optimize=True)   # a new, clean file: no EXIF / GPS, no hidden parts
    return out.getvalue()


def data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


# ---------- 2. safety check of the photo ----------

def check_openai(base_url: str, api_key: str, url: str, caption: str = "", timeout: float = 15) -> Verdict:
    """OpenAI's free moderation check also looks at images (sexual, violence, self-harm)."""
    inputs = [{"type": "image_url", "image_url": {"url": url}}]
    if caption:
        inputs.insert(0, {"type": "text", "text": caption[:1000]})
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/moderations",
            data=json.dumps({"model": "omni-moderation-latest", "input": inputs}).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cats = json.load(resp)["results"][0]["categories"]
    except Exception as exc:
        raise Unavailable(str(exc)) from exc
    for key, category, severity in OPENAI_MAP:
        if cats.get(key):
            return Verdict(category, severity, "model")
    return Verdict(source="model")


def check(moderator, url: str, caption: str = "") -> Verdict:
    """Raises Unavailable when the check can't run. With our own AI checker the reading step does the check."""
    if moderator.provider == "openai":
        return check_openai(moderator.base_url, moderator.api_key, url, caption)
    return Verdict(source="model")


# ---------- 3. reading the question ----------

READ = """You read a photo that a school student in India sent to their teacher in a study app.
Reply with JSON only: {"safe": true, "category": "none", "question": "..."}

Safety first. safe = false if the photo shows any of: nudity or sexual content, gore or injuries, self-harm,
weapons used to hurt, drugs, alcohol or smoking, or anything else not fit for a child. Then category is one of
sexual, violence, self_harm, weapons, drugs, other, and question is "". A textbook picture (history, biology diagram,
a map) is fine.

question = the study question the student wants explained:
- Copy the question text from the photo exactly, in its own language and script (Hindi stays in Devanagari).
- If the student's note points to one question (like "Q3" or "second one"), take only that one; if there are
  several questions and no note, take the first clear one.
- Keep the options of a multiple-choice question.
- A diagram, map or figure without a written question: write a short question such as
  "Explain this diagram of the human heart" in the student's language.
- Maths: write the expression in plain text (x^2 + 3x = 10).
- If you can't read it, or it is not about study at all (a selfie, a room, a screen of a game), question = "".
Never answer the question and never add your own words to it."""


@dataclass
class Reading:
    safe: bool
    category: str
    question: str


def read(vision, url: str, caption: str = "") -> Reading:
    """vision: the model router (A4 switches apply); its client must accept photos."""
    note = f"Student's note: {caption[:300]}" if caption else "No note from the student."
    out = vision.pick().chat_json_image(READ, note, url)
    safe = out.get("safe") is not False
    cat = str(out.get("category") or "other") if not safe else "none"
    q = " ".join(str(out.get("question") or "").split())[:1500] if safe else ""
    return Reading(safe, cat, q)


SEVERITY = {"self_harm": "care"}   # a photo of self-harm gets care, everything else unsafe is serious


def verdict_of(r: Reading) -> Verdict:
    cat = r.category if r.category in ("sexual", "violence", "self_harm", "weapons", "drugs") else "other"
    return Verdict(cat, SEVERITY.get(cat, "serious"), "model")
