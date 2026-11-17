# LiveTeach — AI Safety & Child Protection: Audit and Gap Analysis

**Prepared:** 17 Nov 2026 · **Against:** the owner's brief "AI Teacher Application — Complete Safety, Child Protection & Admin Panel Requirement Report" (kept in `docs/safety-requirements-owner-brief.md`)
**Scope audited:** student app (Flutter), backend (FastAPI + SQLite), AI pipeline (`tutor.py`, `llm.py`, `knowledge.py`), teacher panel, Dhurina admin panel, database schema.
**Status:** analysis only. Nothing in this document has been built yet.

---

## 1. Summary

| Result | Sections |
|---|---|
| Exists (fully or mostly) | 0 |
| Partly exists | 9 — Education-only mode, Human review, AI identity, Privacy, Admin roles, Security, Block/unblock (planned as S1), Web-search safety (setting only), Testing (functional tests only) |
| Missing | 12 — Safety Center, Content filters, Age policies, Input/Output moderation, Warnings, Auto-block, Safety dashboard, Safety test lab, Failure detection, Kill switch, Policy versions, Alerts |
| Not built yet in the app at all (design safety in when built) | Voice, image, video, file questions from students |

**Plain verdict:** today the only safety in the AI is one line in its instructions ("Only help with studies. Never invent facts"). That is not enough for students who are minors.

**Owner's launch rule:** every item in Phases A and B, plus Phase C for any voice / photo / video feature in the launch version, must be done **before launch**. The 12 acceptance criteria in section 24 of the brief are the launch checklist.

### Most important findings
1. **"Topics the AI must not answer" is saved in Admin Settings but never used.** The AI never reads it. An admin would believe something is blocked when it is not. *(Fix first — small.)*
2. **No check before or after the AI.** A student's message goes straight to the AI, and the AI's answer goes straight to the student. Nothing scans either one.
3. **General-AI answers reach the student before anyone checks them.** The teacher reviews them later in "Review answers". The brief says no unchecked answer may reach a minor. A teacher can't approve every live answer in real time, so the realistic rule is: **every answer must pass an automatic safety check before delivery**, and teacher review stays for correctness.
4. **We don't know any student's age or class.** Signup asks only for a phone number. Age-based rules and parent consent are impossible until we collect them.
5. **There is no way to block a student,** neither automatically nor by an admin.
6. **No limits on usage:** unlimited questions per minute, and unlimited OTP SMS requests. This invites abuse and cost.
7. **Conversations are stored as plain text.** There is no retention period and no "delete my data".
8. **There is only one admin role (owner).** A `role` column exists in the database but nothing checks it.
9. **There is no kill switch.** The only control is teacher status (draft / building / live), which is for app builds and does not stop a live AI.
10. **If the AI service fails, the student sees a generic error.** This is "fail closed", which is good, but there is no friendly message and no record of the failure.

---

## 2. Section-by-section gap analysis

Legend: **E** = exists · **P** = partial · **M** = missing · **N** = feature not built yet
Effort: **S** ≤ 1 day · **M** 2–4 days · **L** 1–2 weeks of build work (Claude), plus owner testing time

| # | Requirement | Status | What exists today | Backend | Admin/UI | AI/API | DB | 3rd-party | Effort |
|---|---|---|---|---|---|---|---|---|---|
| 2 | AI Teacher Safety Center (admin section) | M | Settings → "AI answers" card (trusted sites, blocked topics) | — | ✔ new section | — | — | — | M |
| 3 | Content safety & topic blocking (12 categories, strict/medium/relaxed, messages, severity) | M | Blocked-topics list saved but **not enforced** | ✔ | ✔ | ✔ | ✔ settings | moderation model | M |
| 4 | Age-based policies (5–8 … 18+) | M | No age/class stored | ✔ | ✔ app signup + admin | ✔ prompt per age | ✔ students.age_group, class | — | M |
| 5 | Education-only mode, polite redirect | P | One prompt line "Only help with studies"; teacher's "Never does" style rule | ✔ enforce | ✔ topic lists | ✔ | — | — | S |
| 6 | Input → AI → Output moderation, no unchecked answer to a minor | M | None | ✔ new `safety.py` in pipeline | — | ✔ | ✔ safety_events | moderation model | L |
| 7 | Warnings & conversation control (ladder) | M | None | ✔ | ✔ app warning card | — | ✔ violations | — | M |
| 8 | Instant auto-block, enforced at account level | M | None (planned as S1) | ✔ checked on every request | ✔ app blocked screen | — | ✔ students.status | — | M |
| 9 | Admin Block/Unblock management + history | M (planned S1) | Student list per teacher in admin | ✔ | ✔ new page | — | ✔ block_history | — | M |
| 10 | Safety monitoring dashboard | M | Reports dashboard (sales) can be reused as pattern | ✔ aggregates | ✔ | — | uses safety_events | — | M |
| 11 | Human Review Center + escalation, role-limited | P | Teacher "Review answers" queue (correctness, not safety) | ✔ | ✔ | — | ✔ incidents | — | M |
| 12 | AI identity & recording protection | P | Login says "Call your AI teacher"; answers have qa_id + time | ✔ session id, model/policy version, signed audit hash | ✔ "AI" badge on call screen; verify page in admin | — | ✔ | — | M |
| 13 | Voice / image / video / file safety | N | Voice & photo questions not built ("coming soon"); teacher uploads not scanned | ✔ when built | — | ✔ | — | speech-to-text + image moderation | L (with Phase 5) |
| 14 | Privacy & parent control (consent, dashboard, retention, deletion, DPDP) | P | Phones masked; payment keys encrypted; teacher never sees Dhurina share | ✔ | ✔ app consent + admin | — | ✔ consent records, retention job | OTP to parent | L |
| 15 | AI Safety Testing Lab (100–500 scenarios, re-run on change) | M | 53 backend tests + app tests, all functional | ✔ test runner | ✔ admin page with results | ✔ | ✔ test_runs | — | M (+ writing Hindi/Hinglish cases) |
| 16 | Automatic safety-failure detection & corrective tracking | M | None | ✔ part of #6 | ✔ part of #10/#11 | — | ✔ | — | S (after #6) |
| 17 | Emergency kill switch (teacher / voice / image / all chat / model) | M | Teacher status is only for builds | ✔ checked on every request | ✔ big switches + confirm | — | ✔ switches + log | — | S |
| 18 | Safety policy version control, compare, rollback | M | Settings saved without history | ✔ | ✔ | — | ✔ policy_versions | — | M |
| 19 | Roles & permissions (6 roles) | P | role column, only "owner"; confirm popups | ✔ check on every admin API | ✔ Settings → Team | — | ✔ | — | M |
| 20 | Notifications & alerts | M | Toasts only | ✔ | ✔ bell in admin | — | ✔ | email / WhatsApp | M |
| 21 | Security & reliability | P | Admin lockout, JWT, OTP attempt limit, encrypted keys, fail-closed on AI error | ✔ rate limits, encryption at rest, backups, health checks | — | — | ✔ | — | M |

**Overlap with S1** (block/remove teacher, block student, recorded earlier in `safety-requirements.md`): sections 8, 9 and 17 cover it. They will be built together as one feature.

---

## 3. Proposed architecture (simple version)

```
Student message (text now; voice → text later; photo → text + image check later)
   │
   ▼
[0] Account gate ── blocked / suspended / kill switch on?  → stop, show message
   │
   ▼
[1] Input check
   ├─ quick rules: Hindi / Hinglish / English / Punjabi word lists, jailbreak phrases
   └─ moderation model: category + severity
       → safe: continue
       → off-topic: polite "let's study" reply (no AI call, no cost)
       → minor violation: educational redirect + warning count
       → serious: safe refusal + auto-block rule + incident
   │
   ▼
[2] AI teacher (today's tutor) with age-group rules + education-only rules + teacher style
   │
   ▼
[3] Output check (same moderation, stricter for younger ages)
       → unsafe: never shown; replaced by an approved safe reply; incident logged ("AI tried, we stopped it")
   │
   ▼
[4] Deliver + record: session id, AI model, safety-policy version, time, check results
```

- **Fail-safe:** if the moderation step is down or slow, the student gets "Sir will answer in a moment, please try again". The system never skips the check.
- **One place:** a new `backend/app/services/safety.py`. Teacher notes and verified answers also pass the output check, but cost little because verified answers are checked once at approval time.
- **Moderation model options** (choose by cost and Hindi/Hinglish quality on our own test set):
  - a dedicated moderation API from an AI provider;
  - an open safety model hosted by a provider;
  - our own AI asked to classify with a strict JSON answer.

  Word lists alone are not enough, because students mix scripts and spellings.
- **Biology, health and reproduction questions must not be over-blocked.** They are allowed when they fit the student's class level and the syllabus. The test lab includes these cases on purpose.

---

## 4. Suggested plan — three simple phases

### Phase A — before launch (build first)
| # | Item | Why first |
|---|---|---|
| A1 | Enforce education-only + the admin's blocked topics (fixes finding 1) — **built 17 Nov 2026** (see note below) | Small, removes a false sense of safety |
| A2 | Input & output moderation with fail-safe (section 6, 16) — **built 17 Nov 2026** (see note below) | Core protection |
| A3 | Student status + warnings ladder + auto-block at account level + admin Block/Unblock page with history (7, 8, 9, S1) — **built 17 Nov 2026** (see note below) | Stop misuse |
| A4 | Kill switches: all AI chat · one teacher · voice · photo (17) — **built 17 Nov 2026** (see note below) | Emergency control |
| A5 | Session id, AI model, policy version on every answer + admin audit log (12 partial, 21) — **built 17 Nov 2026** (see note below) | Prove what the AI really said if a recording goes viral |
| A6 | Rate limits: questions per minute and per day, OTP sends per number and per device (21) — **built 17 Nov 2026** (see note below) | Abuse + cost |
| A7 | "AI Teacher" badge on the call screen and in notes PDFs (12) — **built 17 Nov 2026** (see note below) | Honest disclosure |
| A8 | Safety test set (~150 cases in Hindi, Hinglish, English, Punjabi), run automatically on every code / prompt / model change; launch blocked if it fails (15) | Proof it works |

**A1 as built:** every AI reply now carries a `scope` (study / off_topic / blocked). The admin's blocked
topics and the education-only rule are in the AI's instructions on every question (admin changes apply at once,
no restart). If the scope is not "study", the model's text is thrown away and never stored; the student gets a
fixed, polite "let's study" message in their language (English / Hindi / Hinglish / Punjabi, else English). The
redirect is logged in `qa_history` (`origin = redirect`, `scope`, `blocked_topic`), is not sent to teacher review,
and cannot be saved as notes. An unknown scope value counts as off-topic (fail closed). Neutral syllabus facts
that only touch a blocked word (e.g. the Constitution under "politics") are allowed with facts only, no opinions —
**owner to confirm**. Limit: this still relies on the AI's own judgement; A2 adds an independent check.

**A6 as built:** all limits are checked on the server and can be changed by the admin in Settings → "Limits"
(apply at once). Defaults: **8 questions a minute and 500 a day per student** — paid students too, so one
account cannot run up AI cost. Counted: questions to Sir, class notes, new tests, written/oral test answers and
"teach again"; MCQ answers are checked without AI and are never limited. A blocked question does not use up a demo
or plan question and is not stored. **OTP:** 30 s between two codes for the same number, 3 per number in 10 min,
10 per number per day, 10 per phone (device) per day, 30 per internet address per hour (generous, because many
mobile users share one address); **10 wrong codes for a number in a day lock it** for the rest of that window (no
new codes, even the right code is refused). The student gets a clear message with how long to wait (HTTP 429 +
Retry-After). The app now sends a random per-install device id and shows the message when "Resend code" is refused.
Limits: the device id and internet address can be changed by an attacker, so the per-number limits are the real
guard on SMS cost; a cloud firewall / Play Integrity (S3) is still needed against large bot attacks. Set
`TRUST_PROXY=1` only behind our own load balancer.

**A3 as built:** every student has a status: **Active · Warning · Suspended (temporary) · Under review · Disabled**.
It is checked on the server for every AI action (question, class notes, test, test answer, "teach again"), so logging
out, reinstalling or starting a new class changes nothing. Suspended / under review: Sir's AI stops, but notes,
library and (except under review) payments keep working. Disabled: nothing works, old logins included.
**What counts:** off-topic chat never counts (a harmless question can never lead to a block). A topic the admin has
blocked = small problem; a clearly harmful request (sexual content, weapons/bombs/drugs, crime, trying to break the
rules, threats) = serious — the AI now marks these as `unsafe`, its text is never shown. **Default ladder** (admin
Settings → "Student safety", can be switched off): 3 blocked-topic questions in 7 days → warning; 6 → suspended 24 h;
1 serious request → suspended 24 h at once; 2 serious in 30 days → stopped until an admin reviews. A suspension ends by
itself; a warning clears after a quiet week. **Admin → Student safety:** list (needs attention / by status / search by
name, phone, ID), student page with what the student wrote, and Warn / Suspend (1–30 days) / Stop until reviewed /
Disable / Unblock — a reason is required, remarks optional; every change (automatic or by whom) is kept in the
history. The app shows the warning or the "AI Teacher paused" message on the call screen. **Care, not punishment:**
a student who shares sadness, bullying or thoughts of self-harm is never marked unsafe; Sir answers warmly, tells
them to talk to a parent / trusted adult and gives Tele-MANAS 14416. Limit: this still relies on the AI's own
judgement; A2 adds an independent check. Not yet: teacher view of flags (owner decision 5), parent notification
(Phase B), a separate admin audit log (A5).

**A2 as built:** an independent safety check (`services/moderation.py`) sits on both sides of the AI teacher.
**Student message:** first free phrase rules (Hindi / Hinglish / English / Punjabi: rule-breaking attempts, porn,
bomb-making, drug-making, clear self-harm words), then the safety model. Harmful → a kind, firm refusal, no AI call,
no demo question used, counts as serious in A3; small problems (insults, someone's private details, risky advice) →
study redirect, minor in A3; sadness / self-harm → a warm fixed reply with Tele-MANAS 14416, never a violation. The
student's chosen name and written / oral test answers are checked the same way. **AI text:** every answer, class
notes, test question and test feedback is checked before it is stored or shown; unsafe → never shown, replaced by a
safe reply ("let me explain in a better way"), logged as "AI answer stopped" (not counted against the student; unsafe
class notes fall back to Sir's already-checked answers). **Fail-safe:** if the checker is down, slow or answers
nonsense, nothing unchecked goes out — "Sir will answer in a moment, please try again", and the demo question is
given back. **Cost:** the same text is never checked twice (cache); provider is chosen by `MODERATION_PROVIDER`:
`llm` (our own AI, cheap small model, understands study context — default when an AI key is set) or `openai` (free
moderation endpoint; "violence" alone is ignored on student messages so history questions aren't blocked). Owner
decision 6 (provider) is still to be made after the A8 Hindi/Hinglish test set. Every event keeps model + policy
version. **Admin → Student safety → "Safety check":** counts for the last 24 h and the latest events (what, result,
category, student, text); a red line warns if the safety model is off. Not yet: per-filter on/off and strict /
medium / relaxed (Safety Center, section 3), alerts to the safety team (B7), incident review workflow (B4).

**A4 as built:** admin → **Emergency** page with one-click switches, checked on the server for every request (no
app update needed): AI chat for all teachers · one teacher's AI · each AI model in use (main / backup / small helper)
· voice and photo (switches ready; those features aren't live yet). While AI is off, students see "Sir is taking a
short break — your notes and library are still open" on the call screen; notes, library and payments keep working
and blocked tries use no demo question. A switched-off model hands its work to the next one in line
(`LLM_BACKUP_MODEL`, optional); with none left, AI chat pauses. Turning off needs "what happened"; turning back on
needs "what did you check" plus a tick that the problem is fixed. Every change is kept in the page's history (who,
when, why). "AI image generation" in the brief does not apply: the app doesn't generate images. Not yet: only certain
roles may use the switches (B5), alert to the team when something is switched off (B7).

**A5 as built:** every answer a student gets (AI answers, refusals, care replies, stopped answers) is sealed when
it is sent: class session, time, the AI model that actually wrote it (or "fixed reply, no AI"), and the safety-policy
version (base policy + fingerprint of the admin's AI / safety / limit settings; every set of rules ever used is kept).
The seal is an HMAC over the exact delivered text and links to the previous seal, so a later change in the database
shows up. Each answer gets a reference code (LT-XXXX-XXXX) shown in small grey text under the answer in the app.
**Admin → Audit → "Check a reported conversation":** paste the code from a screenshot / recording, or some words →
the genuine record (teacher, masked student, session, model, rules) with "Genuine · unchanged" or "Changed after it
was sent"; nothing found → the clip may be edited or fake. **Activity log:** every change in the admin panel and
teacher dashboards (incl. failed tries), and every look at a student's flagged messages or a lookup — who, when,
from which address, what (passwords, keys and codes are never stored); the log is chained and the page shows "Log
intact" or where it was changed. `AUDIT_SECRET` (set once, never change). Limits: an admin with server access could
still rebuild seals with the secret; for stronger proof the seals can later be published / time-stamped outside our
server. Test answers and notes PDFs are not sealed yet (A7 adds the AI badge to PDFs).

**A7 as built:** call screen — an "AI" tag next to the teacher's name and an "AI Teacher" label on Sir's video
(so it is in every screenshot and screen recording); the opening line says plainly "I'm the AI teacher of …, an AI,
not a real person". Notes PDFs (single answer and whole class, every language) — "AI Teacher" label at the top, a
note "Made by the AI teacher of … AI can make mistakes — check important facts with your textbook or teacher", a
faint "AI Teacher" watermark on every page and "AI Teacher" in the footer; a single-answer PDF also carries the
answer's reference code (A5). `/teacher` returns the same disclosure text from the server, ready to be spoken at the
start of a voice / video call (Phase C). Limit: as the brief says, labels can be cropped out of a recording — the
reference code + A5 check is the real proof.

### Phase B — also before launch
| # | Item |
|---|---|
| B1 | Age / class at signup + parent consent by OTP to the parent's phone for under-18s (4, 14). **Legal review needed:** India's DPDP Act 2023 treats everyone under 18 as a child, requires verifiable parental consent, and limits tracking or behavioural monitoring of children. Monitoring for safety must be checked against this with a lawyer. |
| B2 | Age-group policies in the Safety Center (4) |
| B3 | Safety dashboard incl. "AI tried to answer unsafely X times, stopped X times" (10) |
| B4 | Human Review Center with roles; only safety-team roles can see flagged conversations (11, 19) |
| B5 | Team & roles in Settings: Super Admin, Safety Admin, Support, Technical, Auditor (19). "School Admin" maps to **Teacher** in our model. |
| B6 | Encryption of stored conversations, retention period (e.g. auto-delete after N months), delete-my-data request, daily backups (14, 21) |
| B7 | Alerts in the admin panel + email / WhatsApp for serious incidents and spikes (20) |
| B8 | Safety policy versions with compare and rollback (18) |

### Phase C — before launch for any voice / photo / video feature that ships
- Voice: speech-to-text, then the same input check; output check before speaking; AI disclosure spoken at call start.
- Photo questions: image safety check before reading the photo.
- Teacher uploads (PDF / notes / YouTube): scan on upload. A flagged file needs admin approval.
- Optional parent dashboard; recording verification page (paste a session id → see the genuine record).

**Order of build:** A1 → A6 → A3 → A2 → A4 → A5 → A7 → A8, then Phase B.

---

## 5. Decisions needed from the owner before building
1. **Youngest age** the app is for. Should 5–8 year olds be allowed at all, or should the app start at class 6+?
2. **Parent consent:** OTP to the parent's phone at signup? (simplest)
3. **Who is the Safety Team** (names / roles) that can see flagged conversations?
4. **Strictness by default:** strict for everyone under 18? (recommended)
5. **Can a teacher see** the safety flags of his own students, or only Dhurina?
6. **Moderation provider budget:** a small per-question cost may apply; choose after testing on our Hindi/Hinglish set.
7. **Blocked-student message:** use the brief's text as is, or name "Dhurina support"? (Our students don't have a school administrator.)

---

## 6. Honest limits
- No system can promise zero unsafe answers. The checks reduce risk, and the dashboard and test lab show how well they work.
- Watermarks and session ids help prove which recordings are genuine. They cannot stop screen recording.
- Legal compliance (DPDP Act and its Rules) needs a lawyer's review. This document is not legal advice.
