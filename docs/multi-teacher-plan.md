# Multi-teacher + centralized content — agreed plan (17 Nov 2026)

Owner's brief: `docs/multi-teacher-owner-brief.md`. This file is the plan Claude proposed and the owner's additions.
**Start here in a new session:** read this file, then `docs/decisions.md` (rules at the top), then build Step 1.

## Today (before this work)
- One row in `teachers` = one white-label app: Play Store listing, branding, students, plans, Razorpay, split, and notes.
- The notes are in `kb_chunks` (by `teacher_id`), and `verified_answers` are stored per teacher.
- `X-Teacher-Id` header selects the app. The student's JWT carries the teacher id.
- `teacher.html` is a design demo (`IS_DEMO = true`) and is not yet wired to the server.

## Plan (simple, reuse everything; no new panel)
1. **Institute = today's teacher row (the app).**
   - The app, branding, students, plans, payment and split stay as they are. Rename "Teacher" to "Institute / App" in
     the UI only.
   - New: a list of **faculty** (AI teachers) inside an institute. Each faculty has a name, photo/avatar, subject(s),
     subject keywords, teaching style/instructions, a voice id (for later) and active/inactive.
   - A solo teacher is an institute with 1 faculty, so the Subhash Sir app keeps working unchanged (migration creates
     1 faculty per existing teacher).
2. **Automatic teacher switching, with no extra AI cost.**
   - The input safety check already makes a small-model call on every question. Add a `subject` field to that same
     JSON answer, so routing needs no new call. Keyword match on faculty subjects is the free fallback (rules provider).
   - **Sticky:** stay with the current faculty unless the question clearly belongs to another subject. "ok" or
     "aur batao" never switch.
   - The student can say it: "Maths wale sir ko bulao" (phrase lists in the backend and the app; rule 4).
   - The answer carries the active faculty (id, name, avatar url, voice). The switch looks like a call transfer: a
     short fixed handover line, then the new face and name. One chat history per student.
   - Tag `qa_history`, tests and sessions with `faculty_id`, so tests and progress can be shown subject-wise.
3. **One content library per institute.**
   - Upload one file or many at once.
   - **Subject and faculty for each file, in this order:**
     1. The faculty or subject chosen at upload.
     2. A subject in the file or folder name.
     3. One small-model call on the first pages (once per file).
     4. Unsure → "Pending check" in the panel; the admin assigns it in one click.
   - **Search and answers:** search is limited to the faculty's own content plus "general" content. The answer order
     is: verified answers → own content → attached Common Library → general AI.
   - **Kept together:** institute id, faculty id, subject id and file id are stored with every item, so institutes
     never mix.
   - **Safety:** every upload is safety-checked before it goes live (the Phase C "teacher upload" item, done here).
   - **Managing files:** preview, edit, replace and delete, plus manual reassignment.
4. **Common Library (owner, 18:22).**
   - Dhurina's shared library, by subject. Super Admin attaches it to any institute's faculty ("Common content
     jodo"). This is a link, not a copy: new library content reaches every linked faculty. It can be removed in one
     click.
   - The student never sees where content came from: it is always that teacher's voice. Attach and detach are
     written to the audit log.
   - Rule (owner confirmed 17 Nov 2026): only Dhurina's own content, or content whose uploader ticked
     "allow in Common Library", goes into it.
5. **Cross-institute de-duplication (owner, 18:23).**
   - Every file gets a fingerprint of its bytes and one of its normalized extracted text. If the fingerprint already
     exists, the file is not stored again, and the extraction, chunking, classification and safety scan are not run
     again. The institute gets a link to the existing file, and its AI can use it at once.
   - The faculty and subject mapping is stored per link, so each institute assigns the file its own way.
   - Never tell an institute that another one already had the file; it just shows "uploaded".
   - Deleting a file removes only that institute's link. The stored file goes when no link is left.
   - Near-duplicates (around 95% the same) are a later option. Exact file and exact text come first.
   - Common Library and de-duplication share one storage model: files stored once by fingerprint, with link rows for
     each institute and for the Common Library.
6. **Panels.**
   - **Admin panel:** the institute page gets a "Teachers" list and a "Content library" section, plus "Common content"
     for Super Admin.
   - **Institute panel:** wire `teacher.html` to the server (this was pending anyway). It gets teachers and the
     content library.
   - **App:** one new APK, so the name, photo and voice change on a switch. After that, new faculty need no APK,
     because their avatars come from the server.

## Build steps
1. **Server and admin panel:**
   - Faculty, migration, routing (subject in the safety check, sticky, voice command).
   - Storage model (file store, links, de-duplication), library upload and classification, Pending check, Common
     Library.
   - KB search per faculty.
   - Tests for the brief's 7 checks, as a test lab like the safety lab. Prototype: 5 faculty (History, Hindi, English,
     Maths, Reasoning).
2. **App:** active-teacher banner and switch, a new APK via `android.yml`.
3. **Institute panel:** teachers and the content library.

## Status
- **Step 1 (server + admin panel): built** (17 Nov 2026, branch `multi-teacher-step1`).
  - Code: `backend/app/services/faculty.py` (teachers, routing, handover line, call phrases),
    `backend/app/services/library.py` (file store by fingerprint, links, classification, Common Library, per-teacher
    search), `backend/app/teacher_lab.py` (7 checks), tests in `backend/tests/test_multi_teacher.py`.
  - Admin panel: institute page → "Teachers" and "Content library"; menu → "Common content" (Super Admin only) and
    "Multi-teacher tests".
  - Answers now carry `faculty` (id, name, avatar_url, voice_id, subjects), `switched` and `handover`; `/teacher` lists
    the faculty. The app (Step 2) uses these.
  - Subject for switching (owner, 17 Nov 2026, with OpenAI's free safety check): "ok"-type replies never switch →
    free keyword match → when unsure, the search-keyword call the teacher makes anyway (small model) also names the
    subject, remembered per question. No extra AI call.
  - Files: PDF (typed text), Word (.docx), text. Scanned PDFs (photos of pages) wait for Phase C (photo safety + OCR).
  - The institute panel API exists (`/teacher/faculty`, `/teacher/library`); its screens are Step 3.
- **Step 2 (app): built** (17 Nov 2026, branch `step2-app-multi-teacher`). The top name, the face and "<name> is
  thinking…" follow the answering teacher; a switch shows the handover line over the old face, then the new face and
  name fade in. Face = photo from the server, the app's own photo for its own teacher, else the first letter of the
  name. The app opens on the teacher the student was last with (`/me/access` → `active_faculty`). Tests carry their
  teacher. New teachers need no new APK.
- **Step 3 (institute panel): built** (18 Nov 2026, branch `step3-institute-panel`). `/teacher-panel` is now the
  institute's real panel (the demo data is gone): its own login (set / reset by Super Admin on the institute's page,
  one-time password, must change at first login, scrypt hash, 5 wrong = 15 min lock, a new password ends other
  logins); Home (questions, share from own content, active students, own earnings, review waiting); Teachers (add /
  edit / photo / switch off); Content library (upload with progress, folders, Pending check, Text unclear, preview,
  edit, replace, delete); Teaching Style; Review answers; Students & Earnings (own share only); Student safety (own
  flagged students, numbers hidden, read-only, every look audited); Settings (change password). YouTube learning is
  not built yet and is no longer shown.
- **Next:** the owner tests app + panels end to end; fixes first.

## Owner decisions still to confirm (Claude's suggestions)
1. One plan covers all teachers of an institute.
2. Money goes to the institute's Razorpay; Dhurina's share is split as today.
3. Content is uploaded by the institute (Institute panel) and by Dhurina admin.
4. The Common Library holds only Dhurina content and content shared with the uploader's permission.
   (All four: yes. Recorded in `docs/decisions.md`.)

If a Common Library user should pay Dhurina more, use the existing per-teacher split; nothing new is needed.

## Pending after multi-teacher (unchanged order)
1. Safety brief documents (§23).
2. S3 hacking protection.
3. Pausing or blocking a teacher or institute.
4. Phase C: photo and voice safety.
5. Parent dashboard.
6. WhatsApp alerts (last).

Owner items: AI key on Render, SMS provider, SMTP, paid server with a lasting disk, lawyer's DPDP check.
