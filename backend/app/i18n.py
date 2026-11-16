"""Server-side messages (OTP SMS, errors, PDF labels) in every supported language.

Strings missing for a language fall back to English, so a new language can ship before every
message is translated. AI answers are not translated here: the model answers directly in the
student's language.
"""
from .languages import get_language

MESSAGES: dict[str, dict[str, str]] = {
    "otp_sms": {
        "en": "{code} is your LiveTeach code for {teacher}. Valid for 5 minutes.",
        "hi": "{teacher} के LiveTeach के लिए आपका कोड {code} है। 5 मिनट तक मान्य।",
        "pa": "{teacher} ਦੇ LiveTeach ਲਈ ਤੁਹਾਡਾ ਕੋਡ {code} ਹੈ। 5 ਮਿੰਟ ਲਈ ਵੈਧ।",
    },
    "otp_invalid": {
        "en": "That code is not correct. Please try again.",
        "hi": "यह कोड सही नहीं है। कृपया दोबारा कोशिश करें।",
        "pa": "ਇਹ ਕੋਡ ਸਹੀ ਨਹੀਂ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
    },
    "otp_expired": {
        "en": "This code has expired. Please request a new one.",
        "hi": "इस कोड की समय-सीमा खत्म हो गई है। नया कोड मँगाएँ।",
        "pa": "ਇਸ ਕੋਡ ਦੀ ਮਿਆਦ ਖ਼ਤਮ ਹੋ ਗਈ ਹੈ। ਨਵਾਂ ਕੋਡ ਮੰਗੋ।",
    },
    "otp_too_many": {
        "en": "Too many attempts. Please request a new code.",
        "hi": "बहुत ज़्यादा कोशिशें हो गईं। नया कोड मँगाएँ।",
        "pa": "ਬਹੁਤ ਜ਼ਿਆਦਾ ਕੋਸ਼ਿਸ਼ਾਂ ਹੋ ਗਈਆਂ। ਨਵਾਂ ਕੋਡ ਮੰਗੋ।",
    },
    "demo_over": {
        "en": "Your free demo questions are over. Subscribe to keep learning with {teacher}.",
        "hi": "आपके मुफ़्त डेमो सवाल खत्म हो गए। {teacher} के साथ पढ़ाई जारी रखने के लिए सब्सक्राइब करें।",
        "pa": "ਤੁਹਾਡੇ ਮੁਫ਼ਤ ਡੈਮੋ ਸਵਾਲ ਖ਼ਤਮ ਹੋ ਗਏ। {teacher} ਨਾਲ ਪੜ੍ਹਾਈ ਜਾਰੀ ਰੱਖਣ ਲਈ ਸਬਸਕ੍ਰਾਈਬ ਕਰੋ।",
    },
    "notes_title": {"en": "Notes", "hi": "नोट्स", "pa": "ਨੋਟਸ"},
    "notes_question": {"en": "Question", "hi": "प्रश्न", "pa": "ਸਵਾਲ"},
    "notes_source": {"en": "Source", "hi": "स्रोत", "pa": "ਸਰੋਤ"},
    "notes_footer": {
        "en": "Saved from your class with {teacher} · LiveTeach",
        "hi": "{teacher} की क्लास से सेव किया गया · LiveTeach",
        "pa": "{teacher} ਦੀ ਕਲਾਸ ਤੋਂ ਸੇਵ ਕੀਤਾ ਗਿਆ · LiveTeach",
    },
    "source_teacher_notes": {"en": "Sir’s notes", "hi": "सर के नोट्स", "pa": "ਸਰ ਦੇ ਨੋਟਸ"},
    "source_general_ai": {
        "en": "General AI · awaiting teacher review",
        "hi": "सामान्य AI · टीचर की जाँच बाकी",
        "pa": "ਆਮ AI · ਟੀਚਰ ਦੀ ਜਾਂਚ ਬਾਕੀ",
    },
}


def t(key: str, lang: str | None, **kwargs) -> str:
    """Translate a message key into the student's language, falling back to English."""
    entry = MESSAGES[key]
    code = get_language(lang).code
    text = entry.get(code) or entry.get(code.split("-")[0]) or entry["en"]
    return text.format(**kwargs)
