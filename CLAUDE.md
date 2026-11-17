# Working on LiveTeach (Dhurina) — read first

## Talking with the owner
- Reply in Hindi (Devanagari), short: result first, no long recaps. Longer only when asked.
- The owner is not a programmer: plain words, no code in replies unless asked.
- Ask only when a wrong guess would be costly; otherwise decide sensibly and say what you decided in one line.

## Before starting a task
- Product rules and past decisions: `docs/decisions.md` (the "Rules for everything we build" at the top always apply:
  simple first · security tight · low AI cost without losing features · everything can be done on the call).
- Safety work and its order: `docs/safety-gap-analysis.md` (Phase A order: A1 → A6 → A3 → A2 → A4 → A5 → A7 → A8,
  then Phase B). Security plan: S3 in `docs/safety-requirements.md`.
- Read only the files the task needs, and only the parts you need.

## Doing the work
- Backend: `cd backend && python -m pytest -q` (install `requirements.txt` + `httpx` first if needed).
- Flutter can't be built here; the app is checked by GitHub Actions. To check a branch, dispatch
  `android.yml` on it (`gh api -X POST repos/<owner>/<repo>/actions/workflows/android.yml/dispatches -f ref=<branch>`).
- Server-side text and settings over app changes where possible (app updates need a Play Store upload per teacher).
- Every new feature must also work by saying it to Sir on the call (same phrase lists in backend and app).

## Finishing
- When tests pass: commit, push a branch and open a PR yourself (standing permission from the owner) —
  use the REST API (`gh api repos/.../pulls`), GraphQL is blocked. Never push to `main` directly.
- Record new owner decisions in `docs/decisions.md` (one short section, dated).
