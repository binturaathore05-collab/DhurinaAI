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
