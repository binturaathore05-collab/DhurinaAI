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
Only Dhurina admins see flags and the student's words for now (open question 5: teacher access).

## Safety check — A2 (17 Nov 2026)
Built with Claude's choices: every student message and every AI text is checked before it is shown; if the check
can't run, nothing goes out ("please try again"). Default checker = our own AI (small model) because it understands
Hindi / Hinglish and study context; the free OpenAI moderation endpoint is ready as an option. **Owner to decide**
the final provider after testing on the A8 Hindi / Hinglish set (open question 6).

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
