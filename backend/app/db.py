"""Database layer (SQLite for the MVP; the SQL is plain enough to move to PostgreSQL later).

Every table that holds student or teacher data carries teacher_id, so one backend serves every
white-label teacher app while keeping their data apart.
"""
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

CREATE TABLE IF NOT EXISTS rate_events (       -- A6 rate limits: one row per counted event
    key TEXT NOT NULL,                          -- e.g. ask:student:12, otp:phone:<teacher>:<phone>
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS rate_events_key_at ON rate_events (key, at);
"""


class Database:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
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
        ("qa_history", "model", "TEXT"), ("qa_history", "policy_version", "TEXT"), ("qa_history", "prev_hash", "TEXT"),
        ("qa_history", "record_hash", "TEXT"), ("qa_history", "verify_code", "TEXT"), ("qa_history", "sealed_at", "REAL"),
        ("verified_answers", "active", "INTEGER NOT NULL DEFAULT 1"), ("verified_answers", "updated_at", "TEXT"),
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
