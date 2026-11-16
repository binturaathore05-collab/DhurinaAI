"""Languages the app supports.

Every student picks a language once (it can be changed later). That code travels with each request and
decides: the UI strings, the language the AI teacher answers in, the voice used for speech, and the
font used in PDF notes. Adding a language = add one entry here + one UI strings file in the app.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str          # BCP-47 code used everywhere (API, app, TTS)
    english_name: str  # name given to the AI model ("answer in Punjabi")
    native_name: str   # what the student sees in the language picker
    script: str        # ISO 15924 script, used to pick a font for PDFs
    rtl: bool = False


LANGUAGES: dict[str, Language] = {l.code: l for l in [
    Language("en", "English", "English", "Latn"),
    Language("hi", "Hindi", "हिन्दी", "Deva"),
    Language("hi-Latn", "Hinglish (Hindi written in Roman letters)", "Hinglish", "Latn"),
    Language("pa", "Punjabi", "ਪੰਜਾਬੀ", "Guru"),
    Language("bn", "Bengali", "বাংলা", "Beng"),
    Language("gu", "Gujarati", "ગુજરાતી", "Gujr"),
    Language("mr", "Marathi", "मराठी", "Deva"),
    Language("ta", "Tamil", "தமிழ்", "Taml"),
    Language("te", "Telugu", "తెలుగు", "Telu"),
    Language("kn", "Kannada", "ಕನ್ನಡ", "Knda"),
    Language("ml", "Malayalam", "മലയാളം", "Mlym"),
    Language("or", "Odia", "ଓଡ଼ିଆ", "Orya"),
    Language("as", "Assamese", "অসমীয়া", "Beng"),
    Language("ur", "Urdu", "اردو", "Arab", rtl=True),
]}

DEFAULT_LANGUAGE = "hi"

# Noto fonts cover every script above; PDFs list them so the browser picks the right one.
SCRIPT_FONTS = {
    "Latn": "Noto Sans", "Deva": "Noto Sans Devanagari", "Guru": "Noto Sans Gurmukhi",
    "Beng": "Noto Sans Bengali", "Gujr": "Noto Sans Gujarati", "Taml": "Noto Sans Tamil",
    "Telu": "Noto Sans Telugu", "Knda": "Noto Sans Kannada", "Mlym": "Noto Sans Malayalam",
    "Orya": "Noto Sans Oriya", "Arab": "Noto Nastaliq Urdu",
}


def get_language(code: str | None) -> Language:
    """Return the language for a code, falling back to the base language, then the default."""
    if code:
        if code in LANGUAGES:
            return LANGUAGES[code]
        base = code.split("-")[0].lower()
        if base in LANGUAGES:
            return LANGUAGES[base]
    return LANGUAGES[DEFAULT_LANGUAGE]


# ---------- automatic detection: answer in whatever language the student used ----------

_SCRIPT_RANGES = [
    ("Deva", 0x0900, 0x097F), ("Beng", 0x0980, 0x09FF), ("Guru", 0x0A00, 0x0A7F), ("Gujr", 0x0A80, 0x0AFF),
    ("Orya", 0x0B00, 0x0B7F), ("Taml", 0x0B80, 0x0BFF), ("Telu", 0x0C00, 0x0C7F), ("Knda", 0x0C80, 0x0CFF),
    ("Mlym", 0x0D00, 0x0D7F), ("Arab", 0x0600, 0x06FF),
]
_SCRIPT_TO_LANG = {"Deva": "hi", "Beng": "bn", "Guru": "pa", "Gujr": "gu", "Orya": "or", "Taml": "ta",
                   "Telu": "te", "Knda": "kn", "Mlym": "ml", "Arab": "ur"}
# Common Hindi words typed in Roman letters ("Sir Haldighati ka yuddh kab hua tha?")
_HINGLISH = {"hai", "hain", "kya", "kaun", "kab", "kahan", "kyun", "kaise", "tha", "thi", "the", "ka", "ki",
             "ke", "ko", "mein", "me", "se", "aur", "batao", "bataiye", "samjhao", "samjhaiye", "hua", "kiya",
             "yeh", "ye", "woh", "matlab", "nahi", "acha", "accha", "kitne", "kitna", "bhi", "hota", "hoti"}


def detect_language(text: str) -> str:
    """Best guess of the language a question is written in, from its script (and Hinglish words).
    Marathi and Hindi share a script, so Devanagari counts as Hindi here; the AI model still replies in
    the exact language it sees and reports it back."""
    counts: dict[str, int] = {}
    latin = 0
    for ch in text:
        cp = ord(ch)
        if ch.isascii() and ch.isalpha():
            latin += 1
            continue
        for script, lo, hi in _SCRIPT_RANGES:
            if lo <= cp <= hi:
                counts[script] = counts.get(script, 0) + 1
                break
    if counts and max(counts.values()) >= latin / 2:
        return _SCRIPT_TO_LANG[max(counts, key=counts.get)]
    words = {w.strip(".,?!").lower() for w in text.split()}
    the_english = {"the", "is", "was", "what", "who", "how", "why", "of"}
    if len(words & _HINGLISH) >= 2 and len(words & _HINGLISH) > len(words & the_english):
        return "hi-Latn"
    return "en"
