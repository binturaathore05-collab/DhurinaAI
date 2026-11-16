"""Database layer (SQLite for the MVP; the SQL is plain enough to move to PostgreSQL later).

Every table that holds student or teacher data carries teacher_id, so one backend serves every
white-label teacher app while keeping their data apart.
"""
import sqlite3
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
    platform_commission_percent REAL,   -- Durina's share for THIS teacher; teacher gets the rest
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
    platform_percent REAL,              -- Durina's % at the time of this payment
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
    origin TEXT NOT NULL,          -- verified | teacher_notes | general_ai
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
    qa_id INTEGER NOT NULL REFERENCES qa_history(id),
    title TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_id, qa_id)
);
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
    ]

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created."""
        for table, col, typ in self.MIGRATIONS:
            have = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if have and col not in have:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self._conn.commit()

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
