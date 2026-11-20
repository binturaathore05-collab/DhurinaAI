# LiveTeach (Dhurina) — handoff for a new chat (updated 20 Nov 2026)

Read `CLAUDE.md` first (owner's permanent rules), then this file.

## State
- Everything up to PR #46 (resume the class where the student left it) is merged to `main`. No PR is open.
- Built: multi-teacher (Steps 1–3, institute panel with its own login) · audio mode · photo questions + one-time
  "I'm your AI teacher" line · safety Phase A/B · security S3 first part (admin 2-step login, sessions, block list,
  logout everywhere, headers, IP ceiling, obfuscated APK, pip-audit) · pause/block an institute · parent dashboard
  (`/parent`) · profile screen · free plan for testers · test icon · resume the class (#46).
- Tests: 293 backend + 16 app tests pass.

## Next work, in this order (unless the owner says otherwise)
1. Fix whatever the owner finds in testing (screenshots) — always first.
2. "Launch ready?" page in admin: the 12 conditions of §24 of the safety brief checked automatically (green / red).
3. Rooted-phone warning in the app (S3 leftover). Play Integrity and certificate pinning wait for the Play Store
   app and Cloudflare.
4. Only when the owner says the app is ready: one break-it review (numbered problems only, no fixes, then wait)
   and load tests on a local copy with the fake AI (CLAUDE.md rules 5 and 6).

## Open question with the owner (20 Nov 2026)
- Render auto-deploy: the setting is "On Commit" but every deploy shows "Manual", so Render likely doesn't get
  GitHub's push events (the Render GitHub app may not have access to this repo). Owner is checking GitHub →
  Settings → Applications → Render → Repository access. Until fixed: after each merge, Render → Manual Deploy →
  Deploy latest commit.

## Live links (free Render server, region not set = Oregon; the database is wiped on every restart)
- Admin: https://liveteach-demo.onrender.com/admin
- Institute panel: https://liveteach-demo.onrender.com/teacher-panel
- Parent dashboard: https://liveteach-demo.onrender.com/parent
- APK: GitHub Actions → `android.yml` → newest successful run on `main` → artifact `liveteach-demo-apk`
  (ignore `crash-symbols-demo`).
- OTP codes while testing: Render logs, line "[SMS to …]".
- Safety brief deliverables (§23) doc: https://claude.ai/artifact/79RmE9SYqteenZGw1qtADH

## Owner decisions to remember (details in `docs/decisions.md`)
OpenAI free moderation · gpt-4o-mini, $5 prepaid, auto-reload off, `SAFETY_LAB_AUTORUN=0` · audio first, no video
avatar now · WhatsApp later · one plan per institute, money to the institute's Razorpay with Dhurina's split ·
resume: 30-minute rule, gap talk after one whole missed day, AI greeting each time with a safe fallback.
Server: **stay on Render** (owner, 21 Nov 2026; Cloudflare Workers ruled out, Cloudflare only in front). Launch:
Render Starter + 5–10 GB disk, region Singapore; Standard (2 GB) if PDF notes need more memory.

## Owner's launch to-dos (not code)
Paid server with a disk · run the safety lab with the real AI (admin → Safety tests) and add the AI key to GitHub ·
SMS provider with DLT · SMTP · Razorpay live keys · Play Store account · lawyer's DPDP review + privacy/terms links ·
Cloudflare + penetration test · turn on "2-step required" (admin → Security) · new OpenAI key (old one was seen in a
screenshot).
