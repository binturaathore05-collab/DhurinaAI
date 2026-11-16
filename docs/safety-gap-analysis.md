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
| A1 | Enforce education-only + the admin's blocked topics (fixes finding 1) | Small, removes a false sense of safety |
| A2 | Input & output moderation with fail-safe (section 6, 16) | Core protection |
| A3 | Student status + warnings ladder + auto-block at account level + admin Block/Unblock page with history (7, 8, 9, S1) | Stop misuse |
| A4 | Kill switches: all AI chat · one teacher · voice · photo (17) | Emergency control |
| A5 | Session id, AI model, policy version on every answer + admin audit log (12 partial, 21) | Prove what the AI really said if a recording goes viral |
| A6 | Rate limits: questions per minute and per day, OTP sends per number and per device (21) | Abuse + cost |
| A7 | "AI Teacher" badge on the call screen and in notes PDFs (12) | Honest disclosure |
| A8 | Safety test set (~150 cases in Hindi, Hinglish, English, Punjabi), run automatically on every code / prompt / model change; launch blocked if it fails (15) | Proof it works |

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
