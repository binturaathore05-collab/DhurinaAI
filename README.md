# LiveTeach (DhurinaAI)

AI personal-tutor app by Dhurina Ventures Pvt. Ltd. Each teacher gets a white-label app where students
learn with the teacher's AI avatar: ask by voice, text or photo; get answers grounded in the teacher's
own notes; save explanations as PDF notes; subscribe via Razorpay.

## Planned structure

| Folder | What |
|---|---|
| `app/` | Flutter student app (white-label per teacher) |
| `backend/` | Python FastAPI server: auth (OTP), AI/RAG, notes PDF, subscriptions, Razorpay webhooks |
| `dashboard/` | Teacher web panel: upload notes, review AI answers, see subscribers |
| `docs/` | Design and specifications |

## Phase 1 (MVP)
Login with OTP → live class (AI chat + teacher voice) → save notes as PDF → My Library → Pay Now → success.
Video avatar comes in Phase 2.

Secrets (API keys) never go in this repository — they live in a local `.env` file.
