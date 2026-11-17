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
    "plan_ended": {
        "en": "Your plan has ended. Renew to continue learning with {teacher}.",
    },
    "notes_title": {"en": "Notes", "hi": "नोट्स", "pa": "ਨੋਟਸ"},
    "notes_question": {"en": "Question", "hi": "प्रश्न", "pa": "ਸਵਾਲ"},
    "notes_source": {"en": "Source", "hi": "स्रोत", "pa": "ਸਰੋਤ"},
    "notes_footer": {
        "en": "Saved from your class with {teacher} · LiveTeach",
        "hi": "{teacher} की क्लास से सेव किया गया · LiveTeach",
        "pa": "{teacher} ਦੀ ਕਲਾਸ ਤੋਂ ਸੇਵ ਕੀਤਾ ਗਿਆ · LiveTeach",
    },
    "redirect_study": {
        "en": "Let's keep our class about studies. Ask me anything from your syllabus — I'm here to help!",
        "hi": "चलो, अपनी क्लास पढ़ाई पर ही रखते हैं। अपने सिलेबस से कुछ भी पूछो — मैं मदद के लिए हूँ!",
        "hi-Latn": "Chalo, apni class padhai par hi rakhte hain. Apne syllabus se kuch bhi poochho — main madad ke liye hoon!",
        "pa": "ਚਲੋ, ਆਪਣੀ ਕਲਾਸ ਪੜ੍ਹਾਈ 'ਤੇ ਹੀ ਰੱਖਦੇ ਹਾਂ। ਆਪਣੇ ਸਿਲੇਬਸ ਤੋਂ ਕੁਝ ਵੀ ਪੁੱਛੋ — ਮੈਂ ਮਦਦ ਲਈ ਹਾਂ!",
    },
    "test_praise": {
        "en": "Shabash! {score} correct ({pct}%). Excellent work — keep it up!",
        "hi": "शाबाश! {score} सही ({pct}%)। बहुत बढ़िया — ऐसे ही मेहनत करते रहो!",
        "hi-Latn": "Shabash! {score} sahi ({pct}%). Bahut badhiya — aise hi mehnat karte raho!",
        "pa": "ਸ਼ਾਬਾਸ਼! {score} ਸਹੀ ({pct}%)। ਬਹੁਤ ਵਧੀਆ — ਇਸੇ ਤਰ੍ਹਾਂ ਮਿਹਨਤ ਕਰਦੇ ਰਹੋ!",
    },
    "test_good": {
        "en": "Good, {score} correct ({pct}%). Revise these once more: {topics}. We'll continue from here tomorrow.",
        "hi": "अच्छा, {score} सही ({pct}%)। इन्हें एक बार और दोहरा लेना: {topics}। कल यहीं से आगे बढ़ेंगे।",
        "hi-Latn": "Achha, {score} sahi ({pct}%). Inhe ek baar aur dohra lena: {topics}. Kal yahin se aage badhenge.",
        "pa": "ਵਧੀਆ, {score} ਸਹੀ ({pct}%)। ਇਹਨਾਂ ਨੂੰ ਇੱਕ ਵਾਰ ਹੋਰ ਦੁਹਰਾ ਲੈਣਾ: {topics}। ਕੱਲ੍ਹ ਇੱਥੋਂ ਹੀ ਅੱਗੇ ਵਧਾਂਗੇ।",
    },
    "test_reteach_offer": {
        "en": "{score} correct ({pct}%). Most answers were wrong — no problem. Shall I teach {topics} again now?",
        "hi": "{score} सही ({pct}%)। ज़्यादातर जवाब गलत रहे — कोई बात नहीं। क्या मैं {topics} आज दोबारा पढ़ाऊँ?",
        "hi-Latn": "{score} sahi ({pct}%). Zyadatar jawab galat rahe — koi baat nahi. Kya main {topics} aaj dobara padhaun?",
        "pa": "{score} ਸਹੀ ({pct}%)। ਜ਼ਿਆਦਾਤਰ ਜਵਾਬ ਗ਼ਲਤ ਰਹੇ — ਕੋਈ ਗੱਲ ਨਹੀਂ। ਕੀ ਮੈਂ {topics} ਅੱਜ ਦੁਬਾਰਾ ਪੜ੍ਹਾਵਾਂ?",
    },
    "reteach_request": {
        "en": "Sir, please teach me again, simply and step by step: {topics}",
        "hi": "सर, कृपया ये दोबारा आसान तरीके से, एक-एक स्टेप में समझाइए: {topics}",
        "hi-Latn": "Sir, please ye dobara aasan tareeke se, ek-ek step mein samjhaiye: {topics}",
        "pa": "ਸਰ, ਕਿਰਪਾ ਕਰਕੇ ਇਹ ਦੁਬਾਰਾ ਸੌਖੇ ਤਰੀਕੇ ਨਾਲ, ਇੱਕ-ਇੱਕ ਕਦਮ ਸਮਝਾਓ: {topics}",
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
