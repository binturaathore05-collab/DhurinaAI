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
    "limit_ask_minute": {
        "en": "You're asking very fast. Please wait {wait} and ask again.",
        "hi": "आप बहुत तेज़ी से पूछ रहे हैं। {wait} रुककर फिर पूछिए।",
        "pa": "ਤੁਸੀਂ ਬਹੁਤ ਤੇਜ਼ੀ ਨਾਲ ਪੁੱਛ ਰਹੇ ਹੋ। {wait} ਰੁਕ ਕੇ ਫਿਰ ਪੁੱਛੋ।",
    },
    "limit_ask_day": {
        "en": "You've reached today's question limit. Please continue in {wait}.",
        "hi": "आज के सवालों की सीमा पूरी हो गई। {wait} बाद फिर जारी रखिए।",
        "pa": "ਅੱਜ ਦੇ ਸਵਾਲਾਂ ਦੀ ਸੀਮਾ ਪੂਰੀ ਹੋ ਗਈ। {wait} ਬਾਅਦ ਫਿਰ ਜਾਰੀ ਰੱਖੋ।",
    },
    "limit_otp_gap": {
        "en": "A code was just sent. Please wait {wait} before asking for a new one.",
        "hi": "कोड अभी भेजा गया है। नया कोड माँगने से पहले {wait} रुकिए।",
        "pa": "ਕੋਡ ਹੁਣੇ ਭੇਜਿਆ ਗਿਆ ਹੈ। ਨਵਾਂ ਕੋਡ ਮੰਗਣ ਤੋਂ ਪਹਿਲਾਂ {wait} ਰੁਕੋ।",
    },
    "limit_otp": {
        "en": "Too many code requests. Please try again in {wait}.",
        "hi": "बहुत ज़्यादा कोड माँगे गए। {wait} बाद फिर कोशिश करें।",
        "pa": "ਬਹੁਤ ਜ਼ਿਆਦਾ ਕੋਡ ਮੰਗੇ ਗਏ। {wait} ਬਾਅਦ ਫਿਰ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
    },
    "limit_otp_locked": {
        "en": "Too many wrong codes for this number. Please try again in {wait}.",
        "hi": "इस नंबर पर बहुत ज़्यादा गलत कोड डाले गए। {wait} बाद फिर कोशिश करें।",
        "pa": "ਇਸ ਨੰਬਰ 'ਤੇ ਬਹੁਤ ਜ਼ਿਆਦਾ ਗਲਤ ਕੋਡ ਪਾਏ ਗਏ। {wait} ਬਾਅਦ ਫਿਰ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
    },
    "safety_warning": {
        "en": "Please keep our class about studies. If off-limit questions continue, your AI Teacher access will be paused for a while.",
        "hi": "कृपया क्लास को पढ़ाई तक ही रखें। मना किए गए सवाल जारी रहे तो AI Teacher कुछ समय के लिए बंद हो जाएगा।",
        "pa": "ਕਿਰਪਾ ਕਰਕੇ ਕਲਾਸ ਨੂੰ ਪੜ੍ਹਾਈ ਤੱਕ ਹੀ ਰੱਖੋ। ਮਨ੍ਹਾ ਕੀਤੇ ਸਵਾਲ ਜਾਰੀ ਰਹੇ ਤਾਂ AI Teacher ਕੁਝ ਸਮੇਂ ਲਈ ਬੰਦ ਹੋ ਜਾਵੇਗਾ।",
    },
    "safety_suspended": {
        "en": "Your AI Teacher access has been temporarily suspended due to a safety policy violation. It opens again in {wait}. Your notes are still available. For help, contact your parent or Dhurina support.",
        "hi": "सुरक्षा नियम तोड़ने के कारण आपका AI Teacher कुछ समय के लिए बंद किया गया है। यह {wait} बाद फिर खुलेगा। आपके नोट्स खुले हैं। मदद के लिए अपने माता-पिता या Dhurina support से संपर्क करें।",
        "pa": "ਸੁਰੱਖਿਆ ਨਿਯਮ ਤੋੜਨ ਕਾਰਨ ਤੁਹਾਡਾ AI Teacher ਕੁਝ ਸਮੇਂ ਲਈ ਬੰਦ ਕੀਤਾ ਗਿਆ ਹੈ। ਇਹ {wait} ਬਾਅਦ ਫਿਰ ਖੁੱਲ੍ਹੇਗਾ। ਤੁਹਾਡੇ ਨੋਟਸ ਖੁੱਲ੍ਹੇ ਹਨ। ਮਦਦ ਲਈ ਆਪਣੇ ਮਾਪਿਆਂ ਜਾਂ Dhurina support ਨਾਲ ਸੰਪਰਕ ਕਰੋ।",
    },
    "safety_review": {
        "en": "Your AI Teacher access has been suspended due to a safety policy violation and is being reviewed by our team. Your notes are still available. For help, contact your parent or Dhurina support.",
        "hi": "सुरक्षा नियम तोड़ने के कारण आपका AI Teacher बंद किया गया है और हमारी टीम इसकी जाँच कर रही है। आपके नोट्स खुले हैं। मदद के लिए अपने माता-पिता या Dhurina support से संपर्क करें।",
        "pa": "ਸੁਰੱਖਿਆ ਨਿਯਮ ਤੋੜਨ ਕਾਰਨ ਤੁਹਾਡਾ AI Teacher ਬੰਦ ਕੀਤਾ ਗਿਆ ਹੈ ਅਤੇ ਸਾਡੀ ਟੀਮ ਇਸ ਦੀ ਜਾਂਚ ਕਰ ਰਹੀ ਹੈ। ਤੁਹਾਡੇ ਨੋਟਸ ਖੁੱਲ੍ਹੇ ਹਨ। ਮਦਦ ਲਈ ਆਪਣੇ ਮਾਪਿਆਂ ਜਾਂ Dhurina support ਨਾਲ ਸੰਪਰਕ ਕਰੋ।",
    },
    "safety_disabled": {
        "en": "This account has been disabled. For help, contact your parent or Dhurina support.",
        "hi": "यह अकाउंट बंद कर दिया गया है। मदद के लिए अपने माता-पिता या Dhurina support से संपर्क करें।",
        "pa": "ਇਹ ਅਕਾਊਂਟ ਬੰਦ ਕਰ ਦਿੱਤਾ ਗਿਆ ਹੈ। ਮਦਦ ਲਈ ਆਪਣੇ ਮਾਪਿਆਂ ਜਾਂ Dhurina support ਨਾਲ ਸੰਪਰਕ ਕਰੋ।",
    },
    "safety_refusal": {
        "en": "I can't help with that. Our class is a safe place for studies — ask me anything from your syllabus.",
        "hi": "इसमें मैं मदद नहीं कर सकता। हमारी क्लास पढ़ाई के लिए एक सुरक्षित जगह है — अपने सिलेबस से कुछ भी पूछो।",
        "hi-Latn": "Isme main madad nahi kar sakta. Hamari class padhai ke liye ek surakshit jagah hai — apne syllabus se kuch bhi poochho.",
        "pa": "ਇਸ ਵਿੱਚ ਮੈਂ ਮਦਦ ਨਹੀਂ ਕਰ ਸਕਦਾ। ਸਾਡੀ ਕਲਾਸ ਪੜ੍ਹਾਈ ਲਈ ਇੱਕ ਸੁਰੱਖਿਅਤ ਥਾਂ ਹੈ — ਆਪਣੇ ਸਿਲੇਬਸ ਤੋਂ ਕੁਝ ਵੀ ਪੁੱਛੋ।",
    },
    "care_message": {
        "en": "I'm really glad you told me. You matter, and you don't have to go through this alone. Please talk to your mother, father or another adult you trust right now. You can also call Tele-MANAS on 14416 — free, any time, day or night. I'm here for your studies whenever you're ready.",
        "hi": "मुझे खुशी है कि तुमने मुझे बताया। तुम बहुत मायने रखते हो, और तुम्हें यह अकेले नहीं झेलना है। अभी अपनी माँ, पापा या किसी भरोसेमंद बड़े से बात करो। तुम Tele-MANAS को 14416 पर भी फ़ोन कर सकते हो — मुफ़्त, दिन-रात कभी भी। जब तुम तैयार हो, मैं पढ़ाई के लिए यहीं हूँ।",
        "hi-Latn": "Mujhe khushi hai ki tumne mujhe bataya. Tum bahut maayne rakhte ho, aur tumhe yeh akele nahi jhelna hai. Abhi apni maa, papa ya kisi bharosemand bade se baat karo. Tum Tele-MANAS ko 14416 par bhi phone kar sakte ho — muft, din-raat kabhi bhi. Jab tum taiyaar ho, main padhai ke liye yahin hoon.",
        "pa": "ਮੈਨੂੰ ਖੁਸ਼ੀ ਹੈ ਕਿ ਤੁਸੀਂ ਮੈਨੂੰ ਦੱਸਿਆ। ਤੁਸੀਂ ਬਹੁਤ ਮਾਇਨੇ ਰੱਖਦੇ ਹੋ, ਅਤੇ ਤੁਹਾਨੂੰ ਇਹ ਇਕੱਲੇ ਨਹੀਂ ਝੱਲਣਾ। ਹੁਣੇ ਆਪਣੀ ਮਾਂ, ਪਿਤਾ ਜਾਂ ਕਿਸੇ ਭਰੋਸੇਯੋਗ ਵੱਡੇ ਨਾਲ ਗੱਲ ਕਰੋ। ਤੁਸੀਂ Tele-MANAS ਨੂੰ 14416 'ਤੇ ਵੀ ਫ਼ੋਨ ਕਰ ਸਕਦੇ ਹੋ — ਮੁਫ਼ਤ, ਦਿਨ-ਰਾਤ ਕਦੇ ਵੀ। ਜਦੋਂ ਤੁਸੀਂ ਤਿਆਰ ਹੋਵੋ, ਮੈਂ ਪੜ੍ਹਾਈ ਲਈ ਇੱਥੇ ਹਾਂ।",
    },
    "safety_replaced": {
        "en": "Let me explain this in a better way. Please ask your question again, a little differently.",
        "hi": "मैं इसे बेहतर तरीके से समझाता हूँ। कृपया अपना सवाल थोड़ा अलग तरीके से फिर पूछो।",
        "hi-Latn": "Main ise behtar tarike se samjhata hoon. Kripya apna sawaal thoda alag tarike se phir poochho.",
        "pa": "ਮੈਂ ਇਸ ਨੂੰ ਬਿਹਤਰ ਤਰੀਕੇ ਨਾਲ ਸਮਝਾਉਂਦਾ ਹਾਂ। ਕਿਰਪਾ ਕਰਕੇ ਆਪਣਾ ਸਵਾਲ ਥੋੜ੍ਹਾ ਵੱਖਰੇ ਤਰੀਕੇ ਨਾਲ ਫਿਰ ਪੁੱਛੋ।",
    },
    "safety_retry": {
        "en": "Sir will answer in a moment. Please try again.",
        "hi": "सर थोड़ी देर में जवाब देंगे। कृपया फिर से कोशिश करें।",
        "pa": "ਸਰ ਥੋੜ੍ਹੀ ਦੇਰ ਵਿੱਚ ਜਵਾਬ ਦੇਣਗੇ। ਕਿਰਪਾ ਕਰਕੇ ਫਿਰ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
    },
    "ai_paused": {
        "en": "Sir is taking a short break. Please come back in a little while — your notes and library are still open.",
        "hi": "सर थोड़ी देर के ब्रेक पर हैं। कुछ देर बाद फिर आइए — आपके नोट्स और लाइब्रेरी खुले हैं।",
        "pa": "ਸਰ ਥੋੜ੍ਹੀ ਦੇਰ ਦੀ ਬ੍ਰੇਕ 'ਤੇ ਹਨ। ਕੁਝ ਦੇਰ ਬਾਅਦ ਫਿਰ ਆਓ — ਤੁਹਾਡੇ ਨੋਟਸ ਅਤੇ ਲਾਇਬ੍ਰੇਰੀ ਖੁੱਲ੍ਹੇ ਹਨ।",
    },
    "parent_sms": {
        "en": "{code} is the code to allow your child to study with {teacher} on LiveTeach (AI teacher app). Give it to your child only if you agree. Valid 5 minutes.",
        "hi": "{code} आपके बच्चे को LiveTeach (AI टीचर ऐप) पर {teacher} से पढ़ने की अनुमति देने का कोड है। सहमत हों तभी बच्चे को दें। 5 मिनट तक मान्य।",
    },
    "parent_block": {   # B9: never the child's words
        "en": "LiveTeach: {name}'s classes with {teacher} have been paused for a while because the class safety rules were not followed. Please talk to your child. Notes stay open. Help: Dhurina support.",
        "hi": "LiveTeach: सुरक्षा नियम न मानने के कारण {name} की {teacher} वाली क्लास कुछ समय के लिए रोकी गई है। कृपया बच्चे से बात करें। नोट्स खुले हैं। मदद: Dhurina support.",
    },
    "parent_care": {
        "en": "LiveTeach: During class today {name} seemed upset or low. Please talk to your child gently and be with them. If needed, call Tele-MANAS 14416 (free, 24x7).",
        "hi": "LiveTeach: आज पढ़ाई के दौरान हमें लगा कि {name} का मन थोड़ा परेशान या उदास है। कृपया प्यार से बात करें और साथ रहें। ज़रूरत हो तो Tele-MANAS 14416 पर फ़ोन करें (मुफ़्त, 24 घंटे)।",
    },
    "profile_needed": {
        "en": "Please tell us your class first.",
        "hi": "पहले अपनी क्लास बताइए।",
    },
    "consent_needed": {
        "en": "A parent needs to allow LiveTeach first. Enter your mother's or father's phone number to send them a code.",
        "hi": "पहले माता-पिता की अनुमति चाहिए। माँ या पापा का फ़ोन नंबर डालिए, उन्हें एक कोड भेजा जाएगा।",
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


# B9: messages the admin can change in the Safety Center (blank = the text above). Placeholders that must stay.
EDITABLE = {
    "safety_refusal": (), "redirect_study": (), "safety_replaced": (), "safety_warning": (),
    "safety_suspended": ("{wait}",), "safety_review": (), "safety_disabled": (), "care_message": ("14416",),
}
EDIT_LANGS = ("en", "hi", "hi-Latn", "pa")
overrides = {"get": None}   # set by the API: () -> {key: {lang: text}}


def _custom(key: str) -> dict:
    if key not in EDITABLE or not overrides["get"]:
        return {}
    try:
        return {k: v for k, v in ((overrides["get"]() or {}).get(key) or {}).items() if isinstance(v, str) and v.strip()}
    except Exception:   # never break a reply because of a settings problem
        return {}


def validate_messages(values: dict) -> dict:
    out = {}
    for key, langs in (values or {}).items():
        if key not in EDITABLE:
            raise ValueError(f"This message can't be changed: {key}")
        if not isinstance(langs, dict):
            raise ValueError("Each message needs a text per language")
        clean = {}
        for lang, text in langs.items():
            if lang not in EDIT_LANGS:
                raise ValueError(f"Unknown language: {lang}")
            text = str(text or "").strip()
            if not text:
                continue
            if len(text) > 600:
                raise ValueError("A message can be at most 600 letters")
            for must in EDITABLE[key]:
                if must not in text:
                    raise ValueError(f"This message must keep {must}" + (" (the helpline number)" if must == "14416" else
                                                                         " (where the waiting time is filled in)"))
            rest = text.replace("{wait}", "") if "{wait}" in EDITABLE[key] else text
            if "{" in rest or "}" in rest:
                raise ValueError("Please don't use { or } in messages")
            clean[lang] = text
        out[key] = clean
    return out


def t(key: str, lang: str | None, **kwargs) -> str:
    """Translate a message key into the student's language, falling back to English."""
    entry = MESSAGES[key]
    custom = _custom(key)
    if custom:
        entry = {**entry, **custom}
    code = get_language(lang).code
    text = entry.get(code) or entry.get(code.split("-")[0]) or entry["en"]
    return text.format(**kwargs)
