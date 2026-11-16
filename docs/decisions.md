# Product decisions (from planning with Dhurina Ventures)

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
