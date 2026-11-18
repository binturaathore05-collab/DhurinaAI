"""Database layer (SQLite for the MVP; the SQL is plain enough to move to PostgreSQL later).

Every table that holds student or teacher data carries teacher_id, so one backend serves every
white-label teacher app while keeping their data apart.
"""
import os
import sqlite3
from contextlib import contextmanager
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    subject TEXT,
    avatar_url TEXT,
    brand_color TEXT,
    razorpay_key_id TEXT,
    razorpay_key_secret TEXT,
    razorpay_webhook_secret TEXT,
    platform_commission_percent REAL,   -- Dhurina's share for THIS teacher; teacher gets the rest
    app_name TEXT,
    demo_questions INTEGER,             -- NULL = use the default from .env
    grace_days INTEGER,
    grace_questions INTEGER,
    teacher_phone TEXT,
    teacher_email TEXT,
    status TEXT NOT NULL DEFAULT 'draft',   -- draft | building | live
    checklist TEXT,                     -- JSON {item: true/false}
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id TEXT NOT NULL REFERENCES teachers(id),
    phone TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'hi',
    demo_questions_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'active',      -- A3: active | warning | suspended | review | disabled
    status_until REAL,
    status_reason TEXT,
    class_level TEXT,                           -- B1: "6".."12" or "college"
    is_adult INTEGER,                           -- B1: 1 = said they are 18 or older
    consent_status TEXT,                        -- B1: given | withdrawn | NULL
    parent_phone TEXT,
    consent_at REAL,
    UNIQUE (teacher_id, phone)
);
CREATE TABLE IF NOT EXISTS otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id TEXT NOT NULL,
    phone TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    teacher_id TEXT NOT NULL REFERENCES teachers(id),
    name TEXT NOT NULL,
    amount_paise INTEGER NOT NULL,
    duration_days INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    plan_id TEXT NOT NULL REFERENCES plans(id),
    razorpay_order_id TEXT UNIQUE NOT NULL,
    razorpay_payment_id TEXT,
    amount_paise INTEGER NOT NULL,
    platform_percent REAL,              -- Dhurina's % at the time of this payment
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    plan_id TEXT NOT NULL,
    starts_at REAL NOT NULL,
    ends_at REAL NOT NULL,
    payment_id INTEGER REFERENCES payments(id)
);
CREATE TABLE IF NOT EXISTS kb_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_ref TEXT,
    language TEXT,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verified_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    language TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS qa_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    follow_up TEXT,
    origin TEXT NOT NULL,          -- verified | teacher_notes | general_ai | redirect
    sources TEXT,                  -- JSON list
    language TEXT NOT NULL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    password_hash TEXT NOT NULL,          -- scrypt hash, never the password itself
    role TEXT NOT NULL DEFAULT 'owner',
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until REAL,
    last_login TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS admin_logins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    ip TEXT,
    success INTEGER NOT NULL,
    at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS platform_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    qa_id INTEGER REFERENCES qa_history(id),     -- kind = answer: the one answer saved
    title TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    kind TEXT NOT NULL DEFAULT 'answer',         -- answer | class (whole class, topic-wise)
    session_id INTEGER,                          -- kind = class: the class it was made from
    topics TEXT,                                 -- kind = class: JSON list of topics included
    qa_upto INTEGER                              -- kind = class: last answer included (unchanged class = no new AI call)
);
CREATE TABLE IF NOT EXISTS query_rewrites (     -- saves an AI call when a question was asked before
    question TEXT PRIMARY KEY,                   -- normalised question
    query TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS class_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    teacher_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    last_at REAL NOT NULL,
    ended_at REAL
);
CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    teacher_id TEXT NOT NULL,
    session_id INTEGER,
    mode TEXT NOT NULL,                 -- mcq | written | oral
    language TEXT NOT NULL,
    topics TEXT,                        -- JSON list
    questions TEXT NOT NULL,            -- JSON, incl. correct answers: never sent to the app before answering
    results TEXT NOT NULL DEFAULT '[]', -- JSON list, one per answered question
    current INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',  -- open | done
    outcome TEXT,                       -- JSON result: outcome (praise | good | reteach_offer), percent, weak topics
    reteach TEXT,                       -- yes | no (student's answer to "shall I teach it again?")
    created_at REAL NOT NULL,
    finished_at REAL
);

CREATE TABLE IF NOT EXISTS student_violations (  -- A3: what moved a student up the warnings ladder (evidence)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    teacher_id TEXT NOT NULL,
    qa_id INTEGER,
    severity TEXT NOT NULL,                     -- minor | serious
    category TEXT,
    question TEXT,
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS student_violations_student ON student_violations (student_id, severity, at);

CREATE TABLE IF NOT EXISTS student_status_log (  -- A3: every block / unblock, by the system or an admin
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    old_status TEXT,
    new_status TEXT NOT NULL,
    by_who TEXT NOT NULL,                       -- auto | system | admin email
    reason TEXT,
    remarks TEXT,
    until REAL,
    at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS safety_events (     -- A2: every input / output the safety check stopped, or failed on
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    student_id INTEGER,
    teacher_id TEXT,
    stage TEXT NOT NULL,                        -- input | output
    category TEXT,
    severity TEXT,
    source TEXT,                                -- rules | model | cache
    action TEXT NOT NULL,                       -- refused | redirected | care_reply | replaced | retry
    excerpt TEXT,
    model TEXT,
    policy_version TEXT
);
CREATE INDEX IF NOT EXISTS safety_events_at ON safety_events (at);

CREATE TABLE IF NOT EXISTS moderation_cache (  -- A2: the same text is never checked (paid for) twice
    key TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS kill_switches (     -- A4: what is switched off right now
    key TEXT PRIMARY KEY,                       -- all_ai | voice | photo | teacher:<id> | model:<name>
    off INTEGER NOT NULL,
    reason TEXT,
    by_who TEXT,
    at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS kill_switch_log (   -- A4: every switch off / on, who and why
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    off INTEGER NOT NULL,
    reason TEXT,
    by_who TEXT NOT NULL,
    at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_snapshots (   -- A5: every set of safety rules that was ever in force
    version TEXT PRIMARY KEY,
    rules TEXT NOT NULL,
    first_seen REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_audit (        -- A5: who changed what in the admin / teacher panels (chained)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    who TEXT,
    role TEXT,                                  -- admin | teacher
    method TEXT,
    path TEXT,
    status INTEGER,
    ip TEXT,
    details TEXT,                               -- request with secrets removed
    prev_hash TEXT,
    hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS safety_test_runs (  -- A8: every run of the safety test lab
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    mode TEXT NOT NULL,                         -- rules | live
    provider TEXT,
    model TEXT,
    fingerprint TEXT,                           -- AI model + safety settings + instructions this run tested
    policy_version TEXT,
    trigger TEXT,                               -- startup | settings | emergency | admin | ci
    passed INTEGER NOT NULL,
    total INTEGER,
    failed INTEGER,
    groups TEXT,
    failures TEXT,
    seconds REAL
);

CREATE TABLE IF NOT EXISTS parent_consents (  -- B1: proof of every parent's OK (DPDP Act), never deleted
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    teacher_id TEXT,
    parent_phone TEXT NOT NULL,
    given_at REAL NOT NULL,
    ip TEXT,
    notice_version TEXT,
    revoked_at REAL,
    revoked_by TEXT,
    revoke_reason TEXT
);

CREATE TABLE IF NOT EXISTS incidents (         -- B4: safety cases for the review center
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    last_at REAL NOT NULL,
    source TEXT,                                -- auto | admin
    kind TEXT NOT NULL,                         -- care | student_review | serious_request | ai_stopped | report
    severity TEXT NOT NULL,                     -- high | medium | low
    status TEXT NOT NULL,                       -- open | in_review | escalated | resolved
    student_id INTEGER,
    teacher_id TEXT,
    qa_id INTEGER,
    title TEXT,
    summary TEXT,
    events INTEGER NOT NULL DEFAULT 1,
    flagged_by TEXT,
    assigned_to TEXT,
    escalated_at REAL,
    resolution TEXT,
    resolution_note TEXT,
    resolved_by TEXT,
    resolved_at REAL,
    ai_failure INTEGER NOT NULL DEFAULT 0       -- 1 = something unsafe reached the student (dashboard B3)
);
CREATE INDEX IF NOT EXISTS incidents_status ON incidents (status, severity, last_at);

CREATE TABLE IF NOT EXISTS incident_notes (    -- B4: the timeline of every case
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER NOT NULL REFERENCES incidents(id),
    at REAL NOT NULL,
    by_who TEXT NOT NULL,
    action TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS data_jobs (         -- B6: backups and clean-ups that ran
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                         -- backup | retention
    at REAL NOT NULL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS data_requests (     -- B6: delete-my-data requests carried out
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    teacher_id TEXT,
    kind TEXT NOT NULL,
    requested_by TEXT,                          -- student | admin email
    reason TEXT,
    done_at REAL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS retention_tombstones (  -- B6: seal of a deleted answer (no text), keeps the A5 chain whole
    record_hash TEXT PRIMARY KEY,
    deleted_at REAL
);

CREATE TABLE IF NOT EXISTS alerts (            -- B7: what the team is told at once (never a child's words)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    kind TEXT NOT NULL,
    level TEXT NOT NULL,                        -- critical | high | medium
    title TEXT NOT NULL,
    body TEXT,
    link TEXT,                                  -- where in the admin panel
    dedup_key TEXT,
    student_id INTEGER,
    teacher_id TEXT,
    emailed INTEGER NOT NULL DEFAULT 0,         -- 1 sent, -1 failed
    ack_at REAL,
    ack_by TEXT,
    ack_note TEXT
);
CREATE INDEX IF NOT EXISTS alerts_open ON alerts (ack_at, level, at);
CREATE INDEX IF NOT EXISTS alerts_dedup ON alerts (dedup_key, at);

CREATE TABLE IF NOT EXISTS policy_versions (   -- B8: every version of the safety rules, who / when / why
    id INTEGER PRIMARY KEY AUTOINCREMENT,       -- the version number (v1, v2, …)
    created_at REAL NOT NULL,
    created_by TEXT NOT NULL,
    note TEXT,
    rules TEXT NOT NULL,                        -- JSON of the safety sections
    fingerprint TEXT NOT NULL,
    rolled_back_from INTEGER,                   -- set when this version brought back an earlier one
    verified_run INTEGER,                       -- the passing safety-test run (A8) that verified it
    verified_at REAL
);

CREATE TABLE IF NOT EXISTS parent_notices (    -- B9: SMS to a parent (block / care); never the child's words
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    student_id INTEGER NOT NULL,
    kind TEXT NOT NULL,                         -- block | care
    phone TEXT,
    status TEXT NOT NULL,                       -- sent | failed | no_phone | adult | off | repeat
    by_who TEXT NOT NULL                        -- system | admin email
);

CREATE TABLE IF NOT EXISTS rate_events (       -- A6 rate limits: one row per counted event
    key TEXT NOT NULL,                          -- e.g. ask:student:12, otp:phone:<teacher>:<phone>
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS rate_events_key_at ON rate_events (key, at);

-- Multi-teacher: AI teachers (faculty) inside one institute (= one row in teachers = one app)
CREATE TABLE IF NOT EXISTS faculty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id TEXT NOT NULL REFERENCES teachers(id),   -- the institute / app
    name TEXT NOT NULL,
    subjects TEXT NOT NULL DEFAULT '[]',     -- JSON list of subject keys (faculty.SUBJECTS) or "general"
    keywords TEXT NOT NULL DEFAULT '[]',     -- JSON: extra words that mean this teacher ("RAS", "Patwari")
    instructions TEXT,                       -- teaching style / instructions for this teacher
    avatar_url TEXT,
    voice_id TEXT,                           -- for the voice phase
    active INTEGER NOT NULL DEFAULT 1,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at REAL
);
-- One content library: every file stored ONCE by fingerprint; institutes (and the Common Library) get links to it
CREATE TABLE IF NOT EXISTS content_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT UNIQUE NOT NULL,             -- fingerprint of the bytes
    text_hash TEXT,                          -- fingerprint of the normalized extracted text
    size INTEGER NOT NULL,
    kind TEXT NOT NULL,                      -- pdf | txt | docx
    text TEXT NOT NULL,                      -- extracted text (for preview and search)
    ai_subject TEXT,                         -- the one small-model guess (kept, so it never runs twice)
    safety TEXT NOT NULL DEFAULT 'ok',       -- ok | blocked | retry (the check could not run)
    safety_note TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS content_files_text ON content_files (text_hash);
CREATE TABLE IF NOT EXISTS content_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES content_files(id),
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS content_chunks_file ON content_chunks (file_id);
CREATE TABLE IF NOT EXISTS content_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES content_files(id),
    owner TEXT NOT NULL,                     -- institute id, or "common" for Dhurina's Common Library
    title TEXT NOT NULL,                     -- the file name as this owner uploaded it
    subject TEXT,                            -- subject key or "general"; NULL = not decided yet
    faculty_id INTEGER,                      -- a fixed teacher (else every teacher of the subject)
    assigned_by TEXT,                        -- upload | name | ai | admin
    status TEXT NOT NULL DEFAULT 'live',     -- live | pending (subject unsure) | unclear (broken text) | blocked | checking
    allow_common INTEGER NOT NULL DEFAULT 0, -- uploader allows it in the Common Library
    uploaded_by TEXT,
    created_at REAL NOT NULL,
    UNIQUE (file_id, owner)
);
CREATE INDEX IF NOT EXISTS content_links_owner ON content_links (owner, status);
CREATE TABLE IF NOT EXISTS teacher_lab_runs (   -- runs of the multi-teacher test lab (the brief's 7 checks)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    by TEXT,
    mode TEXT NOT NULL,                      -- free (keyword routing) | ai (the real small model)
    passed INTEGER NOT NULL,
    total INTEGER NOT NULL,
    results TEXT NOT NULL                    -- JSON list of checks
);
CREATE TABLE IF NOT EXISTS common_attachments (   -- Common Library subject linked to one institute teacher
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    faculty_id INTEGER NOT NULL REFERENCES faculty(id),
    subject TEXT NOT NULL,
    attached_by TEXT,
    at REAL NOT NULL,
    UNIQUE (faculty_id, subject)
);
"""


class EncryptionError(Exception):
    pass


def _is_plain_sqlite(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _q(key: str) -> str:
    return key.replace("'", "''")


def _encrypt_existing(path: str, key: str) -> None:
    """B6: a plain database is turned into an encrypted one once, when a key is first set (then the plain file goes)."""
    import sqlcipher3
    tmp = path + ".encrypting"
    if os.path.exists(tmp):
        os.remove(tmp)
    c = sqlcipher3.connect(path)
    c.execute(f"ATTACH DATABASE '{_q(tmp)}' AS enc KEY '{_q(key)}'")
    c.execute("SELECT sqlcipher_export('enc')")
    c.execute("DETACH DATABASE enc")
    c.close()
    check = sqlcipher3.connect(tmp)
    check.execute(f"PRAGMA key = '{_q(key)}'")
    check.execute("SELECT count(*) FROM sqlite_master").fetchone()
    check.close()
    os.replace(tmp, path)
    for extra in ("-wal", "-shm", "-journal"):
        if os.path.exists(path + extra):
            os.remove(path + extra)


def connect(path: str, key: str | None = None):
    """Open the database. With a key (DB_ENCRYPTION_KEY) everything on disk — conversations, phone numbers,
    backups — is encrypted (SQLCipher, AES-256); without one it is a normal SQLite file (local development)."""
    if not key:
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    import sqlcipher3
    if path != ":memory:" and os.path.exists(path) and os.path.getsize(path) > 0 and _is_plain_sqlite(path):
        _encrypt_existing(path, key)
    conn = sqlcipher3.connect(path, check_same_thread=False)
    conn.execute(f"PRAGMA key = '{_q(key)}'")
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except Exception as exc:   # wrong key: never start on a database we can't read
        raise EncryptionError("DB_ENCRYPTION_KEY does not open this database (wrong key?)") from exc
    conn.row_factory = sqlcipher3.Row
    return conn


class Database:
    def __init__(self, path: str, key: str | None = None):
        self.path, self.encrypted = path, bool(key)
        self._key = key
        self._conn = connect(path, key)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        self._conn.executescript(SCHEMA)
        self._migrate()

    MIGRATIONS = [
        ("teachers", "razorpay_key_secret", "TEXT"), ("teachers", "razorpay_webhook_secret", "TEXT"),
        ("teachers", "platform_commission_percent", "REAL"), ("teachers", "app_name", "TEXT"),
        ("teachers", "demo_questions", "INTEGER"), ("teachers", "grace_days", "INTEGER"),
        ("teachers", "grace_questions", "INTEGER"), ("teachers", "teacher_phone", "TEXT"),
        ("teachers", "teacher_email", "TEXT"), ("teachers", "status", "TEXT NOT NULL DEFAULT 'draft'"),
        ("teachers", "checklist", "TEXT"), ("payments", "platform_percent", "REAL"),
        ("teachers", "style", "TEXT"), ("students", "name", "TEXT"),
        ("students", "level", "TEXT NOT NULL DEFAULT 'intermediate'"), ("students", "streak", "INTEGER NOT NULL DEFAULT 0"),
        ("qa_history", "emotion", "TEXT"), ("qa_history", "board", "TEXT"), ("qa_history", "emphasis", "TEXT"),
        ("qa_history", "check_result", "TEXT"), ("qa_history", "review_status", "TEXT"),
        ("qa_history", "reviewed_at", "TEXT"), ("qa_history", "verified_id", "INTEGER"),
        ("qa_history", "scope", "TEXT"), ("qa_history", "blocked_topic", "TEXT"),
        ("qa_history", "session_id", "INTEGER"), ("qa_history", "topic", "TEXT"),
        ("qa_history", "notes_worthy", "INTEGER"), ("teachers", "play_store_url", "TEXT"),
        ("saved_notes", "qa_upto", "INTEGER"),
        ("students", "status", "TEXT NOT NULL DEFAULT 'active'"), ("students", "status_until", "REAL"),
        ("students", "status_reason", "TEXT"),
        ("safety_events", "answer_model", "TEXT"),
        ("admin_users", "active", "INTEGER NOT NULL DEFAULT 1"), ("admin_users", "must_change", "INTEGER NOT NULL DEFAULT 0"),
        ("admin_users", "created_by", "TEXT"),
        ("students", "class_level", "TEXT"), ("students", "is_adult", "INTEGER"),
        ("students", "consent_status", "TEXT"), ("students", "parent_phone", "TEXT"), ("students", "consent_at", "REAL"),
        ("qa_history", "model", "TEXT"), ("qa_history", "policy_version", "TEXT"), ("qa_history", "prev_hash", "TEXT"),
        ("qa_history", "record_hash", "TEXT"), ("qa_history", "verify_code", "TEXT"), ("qa_history", "sealed_at", "REAL"),
        ("verified_answers", "active", "INTEGER NOT NULL DEFAULT 1"), ("verified_answers", "updated_at", "TEXT"),
        # multi-teacher: who answered / which teacher a test, class or note belongs to
        ("students", "active_faculty_id", "INTEGER"), ("qa_history", "faculty_id", "INTEGER"),
        ("tests", "faculty_id", "INTEGER"), ("class_sessions", "faculty_id", "INTEGER"),
        ("kb_chunks", "faculty_id", "INTEGER"), ("verified_answers", "faculty_id", "INTEGER"),
        ("moderation_cache", "subject", "TEXT"), ("query_rewrites", "subject", "TEXT"),
        ("content_files", "pages", "INTEGER"), ("content_files", "pages_read", "INTEGER"),
        ("content_files", "unclear", "REAL"),
        # Step 3: the institute's own panel login (set by Super Admin; scrypt hash only)
        ("teachers", "panel_login", "TEXT"), ("teachers", "panel_password_hash", "TEXT"),
        ("teachers", "panel_must_change", "INTEGER NOT NULL DEFAULT 0"), ("teachers", "panel_failed", "INTEGER NOT NULL DEFAULT 0"),
        ("teachers", "panel_locked_until", "REAL"), ("teachers", "panel_pw_changed", "REAL"), ("content_links", "accepted", "INTEGER NOT NULL DEFAULT 0"),
    ]

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created."""
        for table, col, typ in self.MIGRATIONS:
            have = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if have and col not in have:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self._upgrade_saved_notes()
        self._conn.execute("CREATE INDEX IF NOT EXISTS qa_history_verify_code ON qa_history (verify_code)")
        self._conn.commit()

    def _upgrade_saved_notes(self) -> None:
        """Old saved_notes had one row per answer (qa_id required, unique). Class notes need qa_id optional,
        so the table is rebuilt once, keeping every saved note."""
        have = {r["name"] for r in self._conn.execute("PRAGMA table_info(saved_notes)")}
        if "kind" in have:
            return
        self._conn.execute("PRAGMA foreign_keys = OFF")
        self._conn.executescript("""
            ALTER TABLE saved_notes RENAME TO saved_notes_old;
            CREATE TABLE saved_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id),
                qa_id INTEGER REFERENCES qa_history(id),
                title TEXT NOT NULL,
                pdf_path TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                kind TEXT NOT NULL DEFAULT 'answer',
                session_id INTEGER,
                topics TEXT
            );
            INSERT INTO saved_notes (id, student_id, qa_id, title, pdf_path, created_at)
                SELECT id, student_id, qa_id, title, pdf_path, created_at FROM saved_notes_old;
            DROP TABLE saved_notes_old;
        """)
        self._conn.execute("PRAGMA foreign_keys = ON")

    def backup_to(self, path: str) -> None:
        """A consistent copy while the app runs; encrypted with the same key when the database is encrypted."""
        target = connect(path, self._key)
        with self._lock:
            self._conn.backup(target)
        target.close()

    @contextmanager
    def tx(self):
        """Several statements as one step (no other request can slip in between)."""
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()
