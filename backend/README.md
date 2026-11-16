# LiveTeach backend (FastAPI)

## Run locally
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # for PDF notes
cp .env.example .env                 # fill in keys
python seed.py                       # first teacher (Subhash Sir), plans, sample notes
uvicorn app.main:app --reload        # API docs at http://localhost:8000/docs
pytest -q                            # tests
```
On the server also install Noto fonts (`sudo apt install fonts-noto`) so PDFs render every Indian script.

## Languages
The app's screens are always in English. There is no language picker: the AI teacher replies in whatever
language the student asks in — Hindi question → Hindi answer, Punjabi → Punjabi, English → English,
Hinglish → Hinglish — and can switch from one question to the next. `app/languages.py` detects the
question's script; the model also reports the language it replied in (e.g. Marathi vs Hindi). That
language is saved with each answer and used for its voice and its PDF note (right font, right direction).

## API (every call sends `X-Teacher-Id`; student calls also send `Authorization: Bearer <token>`)
| Method | Path | Screen |
|---|---|---|
| GET | `/teacher` | app start: teacher name, photo, colour, plans |
| POST | `/auth/otp`, `/auth/verify` | Login → OTP |
| GET | `/me/access` | demo questions left / subscribed |
| POST | `/class/ask` | Live class: answer + follow-up question; "Sir, save this" saves the last answer |
| POST | `/notes/{qa_id}` | Save button on the popup |
| GET | `/library`, `/notes/{id}/pdf` | My Library: saved notes + question history |
| POST | `/pay/checkout`, `/pay/confirm`, `/pay/webhook` | Pay Now → Razorpay → Payment successful |
| POST/GET | `/teacher/documents`, `/teacher/review`, `/teacher/review/{id}/approve` | Teacher dashboard (`X-Teacher-Key`) |

## How an answer is chosen
1. A teacher-approved (verified) answer to the same question.
2. Otherwise the teacher's own notes (sources shown).
3. Otherwise general AI knowledge, marked "awaiting teacher review" and put in the teacher's review queue.
   When the teacher approves or corrects it, it becomes a verified answer for every future student.

## Payments
The teacher's Razorpay account receives the money; each order carries a Razorpay Route transfer that
sends `PLATFORM_COMMISSION_PERCENT` (default 20%) to Durina's linked account automatically.
