# Backup and restore — how to bring data back (B9)

This is the written procedure the safety brief asks for (section 21: "Backup and recovery procedures").

## What is backed up, and how

- **Every day, automatically.** The server copies the whole database into the backup folder (`BACKUP_DIR`). Files are
  named `liveteach-YYYYMMDD-HHMMSS.db`. The newest 14 are kept; you can change this in admin → Settings → Data keeping.
- **Encrypted.** When `DB_ENCRYPTION_KEY` is set, every backup is encrypted with the same key.
  **Without the key, a backup cannot be read.** Keep the key in two safe places: the hosting settings, plus one
  offline copy with the owner.
- **Tested every week, automatically.** The server opens a copy of the newest backup, the same way a restore would.
  It checks four things:
  1. The key opens it.
  2. The file is not damaged.
  3. The main tables are there: students, teachers, answers, parent consents, payments, audit log, cases and policy versions.
  4. The audit log's seal chain is unbroken.

  If any check fails, an alert is raised (admin → Alerts, and an email when SMTP is set). The last result is shown in
  admin → Data & backups → Restore test. "Test newest backup" there runs the same test immediately. Nothing live is
  changed by a test.
- **Also included:** saved-note PDFs live in `NOTES_DIR`, outside the database. Copy that folder too in your offsite
  backup.

> Demo server (Render free): the backup folder is in `/tmp` and is wiped on every restart. A real server needs a
> lasting disk for the database and `BACKUP_DIR`. It also needs a second copy of the backups somewhere else, such as
> object storage, updated daily.

## When to restore

Restore only when the live database is lost or badly damaged, for example:

- the disk failed;
- the file is corrupted;
- a wrong bulk change cannot be fixed another way.

**Everything written after the backup was taken is lost:** new students, answers, payments and audit entries.
For a single wrong setting, use admin → Safety policy → roll back instead.

## Steps (on the server, about 10 minutes)

1. **Decide and record.** A Super Admin decides. Note the time and the reason; you will add it to the audit trail in step 7.
2. **Pick the backup.** Run this command:
   ```
   python -m app.restore list
   ```
   Choose the newest backup from before the problem started.
3. **Test it.** Run this command:
   ```
   python -m app.restore test liveteach-YYYYMMDD-HHMMSS.db
   ```
   It must print `OK`. If it prints `FAILED`, try the next older backup.
4. **Stop the server.** On Render: Suspend the service, or scale it to 0. Nothing may write to the database during the restore.
5. **Restore.** Run this command:
   ```
   python -m app.restore apply liveteach-YYYYMMDD-HHMMSS.db --yes
   ```
   It checks the backup again first. The current database is kept next to it as `…before-restore-<time>`, so the step
   can be undone.
6. **Start the server.** Then check that it is working:
   - Log in to admin.
   - Open a student page.
   - Check that admin → Audit shows "chain intact".
   - Check that admin → Data & backups shows "Encrypted".
7. **Tell people.** Add a note in admin. If a student-facing problem happened, also note which hours of data were lost.
   Payments made in the lost hours can be found in the Razorpay dashboard and recorded again.

All commands run in the `backend` folder with the server's environment (`DATABASE_PATH`, `BACKUP_DIR`,
`DB_ENCRYPTION_KEY`, `AUDIT_SECRET` / `JWT_SECRET`). The wrong key gives a clear error; it never damages anything.

## Who may do what

| Action | Who |
|---|---|
| Backup now, test a backup, see results (admin → Data & backups) | Super Admin |
| Restore | The server operator, on the Super Admin's decision |
