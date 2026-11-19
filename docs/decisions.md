# Product decisions (from planning with Dhurina Ventures)

## Rules for everything we build (owner, 17 Nov 2026)
1. **Simple first.** Easy for students, teachers and admin: one clear main action per screen, no settings a
   student has to understand, nothing that needs a manual. A new feature that makes a screen harder must be cut down.
2. **Security tight.** Every check happens on the server, never only in the app; no secrets in the app; plan S3
   in `safety-requirements.md` is done before launch.
3. **Low AI cost, never at the cost of features.** It must feel like a real video call with a real teacher, so
   Sir's own replies (even "hi") always come from the AI. Savings only where the student can't notice: commands
   ("save", "test") need no AI; unchanged notes reuse the PDF; search keywords are remembered; MCQ is checked
   without AI; an optional cheaper model (`LLM_SMALL_MODEL`) for helper jobs only; limits per student (A6).
4. **Everything can be done on the call.** Whatever a button does, the student can also just say to Sir in any
   language: "Sir, notes de do", "Sir, MCQ test lo", "viva le lo", … (voice arrives with Phase 5; the same
   sentences already work typed). Buttons stay as a shortcut, not the only way.

- **Brand:** LiveTeach. Each teacher gets a white-label app published on the teacher's own Play Console.
- **Final UI:** "Video Call" design, 6 screens: Login → OTP → Live Class → My Library → Pay Now → Payment Successful.
- **Languages:** app screens stay in English, with no language picker. The teacher automatically answers in
  the language the student speaks or types (Hindi, English, Punjabi, Hinglish, any Indian language).
- **Saving notes:** never a separate screen. During the live call a popup offers "Save", or the student says
  "Sir, save this" (any language). The answer becomes a PDF in My Library.
- **My Library:** saved notes box + full question history.
- **Payment:** single "Pay Now" button → Razorpay. Teacher's merchant account; Dhurina's commission
  split automatically with Razorpay Route. **The split is NOT fixed:** it is chosen per teacher when the
  teacher is added in the admin panel (e.g. 80/20, 75/25, 70/30) and can be changed later.
- **Answer accuracy:** verified answers → teacher's notes → general AI (flagged for teacher review).
- **Tech:** Flutter app, Python FastAPI backend, phases: Phase 1 = chat + teacher voice; Phase 2 = video avatar.

## Roadmap (agreed 16 Nov 2026)
The product is a platform, not one teacher's app. Build everything generic first with a dummy teacher;
real teachers (content, voice, YouTube) are added at the end, only through dashboards — no code changes.

1. White-label student app (Flutter): the 6 Video Call screens wired to the backend, dummy teacher.
2. Dhurina admin panel: add a teacher (name, photo, colour, plans, Razorpay details) → app config generated.
3. Teacher dashboard: upload PDFs/notes/handwritten photos/audio/video, connect own YouTube channel
   (auto-sync), teaching-style profile, answer settings (AI / trusted web fallback), review queue, earnings.
4. Payments, real OTP SMS, demo limit.
5. Teacher voice and video avatar.
6. Onboard the first real teacher and launch.

Build note: this environment can install Python packages but cannot download the Flutter SDK, so the
Android APK is built by GitHub Actions (cloud) and downloaded from the repository's Actions tab.

## Human-like AI teacher (17 Nov 2026)
Full requirements and phase plan: `docs/ai-teacher-requirements.md`. Every tutor answer carries
emotion, emphasis and board points for the voice/avatar phase; Teaching Style (personality, how I
explain, talking with students, avatar settings) is configured per teacher.
- **Teacher never sees Dhurina's share** (17 Nov 2026): in the teacher dashboard and teacher reports only the
  total paid, the teacher's own % and the teacher's own earnings appear — no Dhurina % or amount anywhere.
  The admin panel keeps the full split. Reports show "Period: <from> to <to>" in Indian time.

## Class notes, test series, sharing (owner, 17 Nov 2026)
- **Notes = the whole class, topic-wise.** A class runs from the first question until "End class" (or 30 minutes
  with no question). "Save" or "Sir, save this" makes ONE PDF for the whole class: greetings, thanks, small talk and
  off-topic replies are left out; the AI arranges the rest under one heading per topic, using only what Sir said.
  The student can untick topics ("Choose topics"). Saving again in the same class updates that PDF, not a new one.
  If the AI is down, the PDF is still made from Sir's answers as they were.
- **Test series.** Sir gives a test on what he taught: at "End class" ("Quick test before you go?") or any time
  the student asks ("Sir, test lo" in any language, or the test button). The student picks **MCQ** (4 options,
  checked instantly), **Written** (short answers, AI checks the key points, half marks possible) or **Oral / viva**
  (Sir asks one by one; typed for now, spoken with the voice update). Questions come only from that class. After
  each answer: right / wrong, why, and the right answer. At the end: **below 50% → "Shall I teach it again?"
  Yes / No** (Yes = Sir re-teaches the weak topics right away); **80%+ → shabash**; in between → "good, revise
  these". Defaults (10 questions, 50%, 80%) live in Admin Settings → `tests`. A test counts as one question of
  the plan / demo. Correct answers never reach the app before the student answers.
- **Share.** A share button in the class (share the app), on every saved note (sends the PDF) and on the test
  result (score). Every share carries one link: `<PUBLIC_BASE_URL>/t/<teacher id>` — a small page with the
  teacher's photo and a "Get the app on Google Play" button. Admin enters the teacher's Play Store link (only real
  play.google.com links or a package id are accepted); until then the page says "coming soon".

## Ask before risky actions (everywhere: app, teacher panel, admin panel)
Nothing that is hard to undo happens on one tap. A popup asks first; **Cancel** is the default
(focused, Enter / Esc / tap outside = Cancel).
- Admin: log out · change a teacher's split (shows old → new, new payments only) · save & build app ·
  build new version · save settings (money changes highlighted) · change password · leaving a form with unsaved changes.
- Teacher: delete a file · disconnect YouTube · turn off auto-sync · mark an answer wrong · bulk approve/reject
  (20+ needs "I have checked" tick) · move an answer back to Waiting · replace an approved answer · discard an edit ·
  leaving Teaching Style / a note / an edit unsaved · change password · log out.
- Student app: End class · phone back button (leave class) · closing the screen while a payment is in progress.
Any new risky action must use the same `ask()` (web) / `confirmAction()` (app).


## Launch rule (owner, 17 Nov 2026)
**All safety work must be finished before launch** — Phase A *and* Phase B of `docs/safety-gap-analysis.md`,
plus Phase C for any voice / photo / video feature that is in the launch version. The 12 acceptance criteria in
section 24 of the owner's brief are the launch checklist. No real student uses the app until every item passes.

## Rate limits — A6 (17 Nov 2026)
Built with sensible defaults (Claude's choice, owner can change them any time in admin Settings → Limits):
8 questions a minute and 500 a day per student, including paid students (cost guard; MCQ answers never count);
OTP: 30 s gap, 3 per number per 10 min, 10 per number per day, 10 per device per day, 30 per internet address per
hour; 10 wrong codes lock a number for the day. Owner confirmed (17 Nov 2026): **500 questions a day** per student, paid students included.

## Student safety ladder — A3 (17 Nov 2026)
Built with Claude's defaults (owner can change them in admin Settings → "Student safety"): off-topic chat never
counts; blocked topic = small problem, clearly harmful request = serious; 3 small in 7 days → warning, 6 → 24 h
suspension; 1 serious → 24 h suspension, 2 serious in 30 days → stopped until an admin reviews. Notes and library
stay open while suspended. Blocked-student message names "your parent or Dhurina support" (open question 7).
Flags and the student's words: Dhurina admins **and** the student's own teacher (owner, 17 Nov 2026; see below).

## Safety check — A2 (17 Nov 2026)
Built with Claude's choices: every student message and every AI text is checked before it is shown; if the check
can't run, nothing goes out ("please try again"). Default checker = our own AI (small model) because it understands
Hindi / Hinglish and study context; the free OpenAI moderation endpoint is ready as an option. **Owner decided
(17 Nov 2026): use the free OpenAI check for now**, change later if needed (see below).

## Emergency switches — A4 (17 Nov 2026)
Any admin can switch off AI chat (all / one teacher / one model) and voice / photo at once; turning back on needs a
note of what was checked. Optional backup model (`LLM_BACKUP_MODEL`) takes over when the main model is off. Limiting
the switches to certain roles waits for Team & roles (B5).

## Proof & audit — A5 (17 Nov 2026)
Every answer shows a small reference code (LT-XXXX-XXXX) in the app, so a viral clip can be checked in admin →
Audit. Every admin / teacher-panel change and every look at flagged student messages is logged (no passwords or keys).

## AI disclosure — A7 (owner, 17 Nov 2026)
Don't show "AI Teacher" / "AI" labels everywhere — the student must feel it is a real class. Tell it once at the start
(login screen: "Call your AI teacher, anytime") and put it in the policy / terms. No label on the video, no AI note or
watermark on notes PDFs; PDFs keep only the small reference code (A5).

## Safety tests — A8 (17 Nov 2026)
Launch is blocked until the safety tests pass with the AI model and safety settings actually in use (admin → Safety
tests shows "Launch: ready / blocked"). Pass rules: every harmful request stopped, every upset student cared for, at
least 97% of study questions answered. The tests re-run by themselves on every model / settings / code change.

## Who can use the app — B1 (owner, 17 Nov 2026)
Class 6 and above (admin can change the lowest class). Students under 18 need a parent's OK: an OTP sent to the
parent's phone, before Sir's AI works. 18+ students start straight away. The class is asked once at signup and Sir
explains at that level.

## Age-group rules — B2 (17 Nov 2026)
Claude's defaults, editable in admin Settings → Age groups: Class 6–8 strict (no romance / dating, horror / gore),
Class 9–10 medium (no dating advice), Class 11–12 medium, 18+ relaxed. Syllabus questions are answered in every group.

## Team & roles — B5 (17 Nov 2026)
Five admin roles (Super Admin, Safety Admin, Support, Technical, Auditor), Claude's split of permissions — see
`backend/app/services/roles.py` and admin → Team. Only Super Admins manage the team and money settings; only Super /
Safety Admins see student conversations or block students. New members get a one-time password.

## Data keeping — B6 (17 Nov 2026)
Owner didn't pick a period; Claude used its suggestion: conversations 12 months, safety records 36 months, then
deleted by themselves (admin Settings → Data keeping). Students can delete their account and data themselves (app or
by telling Sir). Database and backups encrypted.

## Safety Center, filters, parent SMS, restore — B9 (17 Nov 2026)
Owner asked to close the gaps found against the brief. Claude's choices: five child-protection filters (sexual,
weapons, drugs, self-harm, rule-breaking) can never be turned off or lowered; turning another filter off only affects
students' messages, never Sir's answers. Parent SMS on block: on by default. Parent SMS for an upset student: a person
decides in the case by default (sometimes the trouble is at home), admin can make it automatic. Parent SMS in Hindi by
default. Backups are restore-tested automatically every week.

## Multi-teacher institutes (owner, 17 Nov 2026)
One app can hold many AI teachers (an institute); Sir switches teacher by the question's subject; all content in one
library, classified by AI. Owner added: a Dhurina Common Library that Super Admin can attach to a teacher with little
content, and files identical across institutes are stored and processed only once. Plan and open questions:
`docs/multi-teacher-plan.md`.

## Owner answers, 17 Nov 2026 (evening)
- **One plan per institute:** one plan / payment covers all teachers of an institute.
- **Money:** goes to the institute's Razorpay; Dhurina's share is split automatically as today.
- **Content upload:** both the institute (Institute panel) and Dhurina admin can upload.
- **Common Library:** only Dhurina's own content, and content whose uploader ticked "allow in Common Library".
- **Safety check provider:** the free OpenAI moderation check for now; change later if needed. Built as the default
  (`MODERATION_PROVIDER=auto` → OpenAI when an OpenAI key is on the server: `OPENAI_MODERATION_KEY`, or the AI key when
  the AI is OpenAI; otherwise our own AI checker). To go back: `MODERATION_PROVIDER=llm`. The safety tests (A8) re-run
  with it by themselves and still decide "Launch: ready / blocked". With OpenAI's check, the multi-teacher subject is
  found by the free keyword match (OpenAI's check gives no subject).
- **Flagged messages:** Dhurina's safety team **and** the student's own teacher can see them. The teacher sees only
  their own app's students, can't block or unblock, and every look is written to the audit log
  (`/teacher/safety`; the screen comes with the Institute panel).


## Testing phase: lowest AI bill (owner, 17 Nov 2026)
While we are testing, keep the OpenAI bill as low as possible: $5 prepaid, auto-reload off (spending stops at $0).
Demo server: `LLM_MODEL=gpt-4o-mini` for everything (no separate small model), free OpenAI safety check,
`SAFETY_LAB_AUTORUN=0` (the 160-case safety test runs only when someone presses it in admin, not on every restart of
the free server). Any test Claude runs with the real AI uses the fewest calls needed; bigger models only after testing.

## Audio first, video avatar later (owner, 17 Nov 2026)
No video / AI avatar for now. The app is built and tested end to end in **audio**: the student speaks or types, Sir
answers in voice (and text). Questions, answers, notes and tests all work in audio mode first; video mode comes
later, after a small cost trial of avatar providers (per-minute billing). While testing, voice uses the phone's own
free speech-to-text and text-to-speech; the teacher's own cloned voice is a later step.

## Free plan without payment, for testers (owner, 18 Nov 2026)
Payments are not set up yet, so testers would stop after the 3 demo questions. Super Admin can now give any student a
plan without payment (admin → Student safety → the student → Plan → "Give free plan", days + why) and end it again.
It never counts as money or as a paying plan in reports; every change is in the audit log. Also usable later for
scholarships. On the free demo server it is lost when the server restarts.

## Institute panel login (Claude, 18 Nov 2026 — owner can change)
Each institute logs in to `/teacher-panel` with its own login (email or mobile) and password. Super Admin creates it
and resets it on the institute's page (admin → Institutes / Apps → the institute → "Institute panel login"); a
one-time password is shown once and must be changed at the first login. The institute sees only its own students
(numbers hidden), its own share of the money, and its own flagged students (read-only; every look is in the audit log).


## Photo questions and the one-time AI line — Phase C (Claude, 18 Nov 2026 — owner can change)
Owner asked to start Phase C. **Photo questions:** the camera button (or saying "photo se poochna hai") → camera or
gallery → optional note ("Q3 samjhao") → Sir answers. On the server: only a real photo, made smaller and saved again
without location data; a safety check of the photo (OpenAI's free image check; our own AI's check otherwise) before
anything reads it; then one AI call copies the question from the photo (it never answers), and that question goes
the normal way (text check → right teacher → answer check). An unsafe photo counts like an unsafe message (A3).
**The photo is never stored**, only the question read from it. Limit: 30 photos per student per day (admin →
Settings → Limits); admin → Emergency → "Photo questions" switches it off. Cost: about ₹0.3 per photo with gpt-4o-mini.
**AI line:** following A7 (tell once, no labels everywhere), Sir says "Namaste! I'm …, your AI teacher" only at the
student's very first class (on screen and spoken), never again.

## Security, first part — S3 (Claude, 18 Nov 2026 — owner can change)
Owner asked to start security. Built the simple version first: 2-step login for the admin team (authenticator app;
**not required yet** during testing — Super Admin can switch "Required for everyone" on in Admin → Security; turn it on
before launch), logged-in devices with "log out other devices", alert on a login from a new place, block list for
numbers and IP addresses (IP blocks end by themselves because many students share one mobile-network IP), "log out on
other phones" for students, OTP-flood and password-guessing alerts, browser security headers, a request ceiling per IP,
obfuscated APK and a library security scan. Old admin logins end once after this update (log in again).

## Pause or block an institute (Claude, 18 Nov 2026 — owner can change)
Only the Super Admin can do it (Admin → Institutes / Apps → the institute → Institute status), always with a reason the
institute sees. **Pause** (e.g. Dhurina's fees due; can end by itself after 1–30 days): Sir's AI stops for its
students and no new plans can be bought; notes, library, sign-ups and the institute panel stay open (a banner shows the
reason). **Block** (serious problem): as pause, plus no new students, the institute panel is closed and no new app
builds. Nothing is ever deleted; "Make active again" brings everything back. Every change is in a history, the audit
log and raises an alert. One AI teacher inside an institute is still switched off in the Teachers list.

## Parent dashboard (Claude, 18 Nov 2026 — owner can change)
A web page, no app needed: `<server>/parent`. The parent types the mobile number that gave consent and the SMS code
(sent only to numbers that are a parent's on record, so no SMS cost for others) and sees each child: study this week,
questions per day (14 days), topics learnt, test results, plan, consent and account status — **never the child's own
words or Sir's answers** (same rule as the parent SMS). Hindi first, English switch. DPDP rights on the page: withdraw
consent (Sir stops for the child) and delete the child's data (type DELETE). The student can send the link from
Profile → "Send the parent dashboard to my parent" (or say "parent dashboard" to Sir). Parent logins and actions are kept.

## Permanent rules for every feature (owner, 18 Nov 2026)
Saved in `CLAUDE.md`: tests first and shown failing, then code; never change a test just to pass it; unit tests
(happy path, edge cases incl. Hindi/Unicode, errors) and end-to-end flows incl. failures; "done" only with the real
test output shown; after every feature a break-it review (numbered problems only, no fixes, then wait for the owner);
real load tests (100 / 1,000 / 5,000 students) with response times, errors and AI cost per 1,000 users; explain why;
if unsure, ask — don't guess. Also decided: WhatsApp alerts later.
**When (owner, 19 Nov 2026, to keep usage low):** tests-first, shown output, explain why and ask-when-unsure apply
now; the break-it review and the load tests are done once for the whole app when it is ready, before launch.
