# Working on LiveTeach (Dhurina) — read first

## Talking with the owner
- Reply in Hindi (Devanagari), short: result first, no long recaps. Longer only when asked.
- The owner is not a programmer: plain words, no code in replies unless asked. Exception: the actual test run
  output (rule 4 below) is always shown.
- Explain WHY each important decision was made, in simple words, so the owner learns.
- If you are unsure about something, ask the owner. Don't guess. (Owner rule, 18 Nov 2026 — replaces the older
  "decide sensibly unless a wrong guess is costly".)

## Owner's permanent rules for every feature (18 Nov 2026)

**When they apply (owner, 19 Nov 2026 — to keep usage low):** rules 1–4 and 7 apply now, to every feature.
Rules 5 (break-it review) and 6 (load testing) are done ONCE for the whole app when all features are ready, before
launch — not after each feature. Don't start them before the owner says the app is ready.

### 1. Test-driven development (mandatory)
- Before writing any feature code, write the tests first.
- Run them and show the owner they FAIL. Then write the code to make them pass.
- Never change or delete a test just to make it pass. If a test seems wrong, stop and ask the owner.

### 2. Unit tests
- Every function, API route and component gets unit tests.
- Cover the happy path, edge cases (empty input, very long input, special characters, Hindi/Unicode text) and
  error cases.

### 3. Integration tests
- Test full flows end to end: signup → login → start lesson → ask the tutor a question → get answer → save progress.
- Include failures: AI API timeout or error, database down, network loss, expired session.

### 4. "Done" means
- All tests pass, and the owner is shown the actual test run output.
- Never say a feature is complete without that output.

### 5. Break-it review (once, when the app is ready — see "When they apply")
Once the app is done, switch roles: you are now a security tester and penetration tester. Your job is to BREAK
the app.
- Give the owner ONLY a numbered list of problems. DO NOT FIX ANYTHING.
- For each point: what breaks, how to reproduce it, severity (Critical / High / Medium / Low).
- For this AI Tutor app, check especially:
  - Prompt injection: can a student make the tutor ignore its instructions, reveal the system prompt, or give exam
    answers it shouldn't?
  - Unsafe or wrong content: can the tutor be pushed into inappropriate content (students may be minors) or
    confidently wrong answers?
  - Data leaks: can one student see another student's chats, progress or personal data?
  - Auth: weak login, session theft, missing permission checks on APIs.
  - Cost abuse: can someone spam the AI API and run up the bill? Is there rate limiting?
  - Secrets: any API keys in frontend code, logs or the git repo?
  - Payments: can premium features be unlocked without paying?
- Then wait. The owner discusses the points one by one and decides the fix order.

### 6. Load testing (once, when the app is ready)
- Don't just "imagine" thousands of users. Write a real load-test script (k6 or Locust) that simulates 100, then
  1,000, then 5,000 concurrent students using the main flows.
- Run it and report: response times, error rate, what broke first, and the estimated AI API cost per 1,000 users.

### 7. Always
- Explain WHY you made each important decision, in simple words.
- If you are unsure about something, ask. Don't guess.

### How these rules work in this repo
- Backend tests: `cd backend && python -m pytest -q` (install `requirements.txt` + `httpx` first if needed). For
  rule 1, run the new test file alone first and show its failures, then the whole suite after the code.
- App (Flutter) tests can't run here: they run on GitHub Actions (`android.yml` runs analyze + `flutter test`).
  For rule 1 on app code, push the tests first, dispatch the workflow, show the failing run, then push the code.
- Integration tests use FastAPI's TestClient with the fake AI (`FakeLLM`); AI failures, database errors and
  expired sessions are simulated there, so no real AI money is spent.
- Load tests run against a local copy of the server with the fake AI. Never against the live Render server or the
  real AI key unless the owner says so (cost, and the free server can't take it). The AI cost per 1,000 users is
  worked out from the token counts and the model's price, and shown as an estimate.

## Before starting a task
- Product rules and past decisions: `docs/decisions.md` (the "Rules for everything we build" at the top always apply:
  simple first · security tight · low AI cost without losing features · everything can be done on the call).
- Safety work and its order: `docs/safety-gap-analysis.md` (Phase A order: A1 → A6 → A3 → A2 → A4 → A5 → A7 → A8,
  then Phase B). Security plan: S3 in `docs/safety-requirements.md`.
- Read only the files the task needs, and only the parts you need.

## Doing the work
- Flutter can't be built here; the app is checked by GitHub Actions. To check a branch, dispatch
  `android.yml` on it (`gh api -X POST repos/<owner>/<repo>/actions/workflows/android.yml/dispatches -f ref=<branch>`).
- Server-side text and settings over app changes where possible (app updates need a Play Store upload per teacher).
- Every new feature must also work by saying it to Sir on the call (same phrase lists in backend and app).

## Finishing
- When tests pass (and the output was shown): commit, push a branch and open a PR yourself (standing permission
  from the owner) — use the REST API (`gh api repos/.../pulls`), GraphQL is blocked. Never push to `main` directly.
- Record new owner decisions in `docs/decisions.md` (one short section, dated).
