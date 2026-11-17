"""Settings read from environment variables (see .env.example). No secrets live in code."""
import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    database_path: str = field(default_factory=lambda: _env("DATABASE_PATH", "liveteach.db"))
    jwt_secret: str = field(default_factory=lambda: _env("JWT_SECRET", "change-me"))
    jwt_days: int = field(default_factory=lambda: int(_env("JWT_DAYS", "30")))
    demo_question_limit: int = field(default_factory=lambda: int(_env("DEMO_QUESTION_LIMIT", "3")))
    # After a plan ends: a short grace period so studies don't stop mid-way (set either to 0 to disable)
    grace_days: int = field(default_factory=lambda: int(_env("GRACE_DAYS", "2")))
    grace_questions: int = field(default_factory=lambda: int(_env("GRACE_QUESTIONS", "3")))
    renew_reminder_days: int = field(default_factory=lambda: int(_env("RENEW_REMINDER_DAYS", "3")))

    # AI model (any OpenAI-compatible chat + embeddings API)
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "https://api.openai.com/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL"))
    llm_small_model: str = field(default_factory=lambda: _env("LLM_SMALL_MODEL"))  # optional, for helper jobs
    # optional: used when the main model is switched off in admin → Emergency (same API, another model)
    llm_backup_model: str = field(default_factory=lambda: _env("LLM_BACKUP_MODEL"))

    # Razorpay defaults. Each teacher's own keys and commission split are stored per teacher (admin panel);
    # these are only used for a teacher who has none set.
    razorpay_key_id: str = field(default_factory=lambda: _env("RAZORPAY_KEY_ID"))
    razorpay_key_secret: str = field(default_factory=lambda: _env("RAZORPAY_KEY_SECRET"))
    razorpay_webhook_secret: str = field(default_factory=lambda: _env("RAZORPAY_WEBHOOK_SECRET"))
    platform_linked_account: str = field(default_factory=lambda: _env("PLATFORM_LINKED_ACCOUNT"))
    platform_commission_percent: float = field(default_factory=lambda: float(_env("PLATFORM_COMMISSION_PERCENT", "20")))

    # SMS provider for OTP (plug in MSG91 / Twilio / etc. in services/sms.py)
    sms_provider: str = field(default_factory=lambda: _env("SMS_PROVIDER", "console"))

    # Public address used in share links: <PUBLIC_BASE_URL>/t/<teacher id> (e.g. https://liveteach.in)
    public_base_url: str = field(default_factory=lambda: _env("PUBLIC_BASE_URL") or _env("RENDER_EXTERNAL_URL"))

    # Set TRUST_PROXY=1 only when the API runs behind our own proxy / load balancer (then the student's IP is
    # read from X-Forwarded-For for the OTP-per-IP limit). Off by default, because the header can be faked.
    trust_proxy: bool = field(default_factory=lambda: _env("TRUST_PROXY", "0") == "1")

    # A2 safety check: auto (= llm when an AI key is set, else rules only) | llm | openai | rules
    moderation_provider: str = field(default_factory=lambda: _env("MODERATION_PROVIDER", "auto"))

    # A5: seals answer records and the admin audit log. Set once, keep secret, never change (old seals would no
    # longer verify). Empty = derived from JWT_SECRET.
    audit_secret: str = field(default_factory=lambda: _env("AUDIT_SECRET"))

    # B6: encrypt the whole database (and so every backup). Set once to a long random value and keep it safe:
    # without it the data can't be read. Empty = not encrypted (local development only).
    db_encryption_key: str = field(default_factory=lambda: _env("DB_ENCRYPTION_KEY"))
    backup_dir: str = field(default_factory=lambda: _env("BACKUP_DIR", "backups"))

    # B7: email for alerts (any SMTP: Gmail app password, Zoho, Amazon SES …). Empty host = alerts only in the panel.
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(_env("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD"))
    smtp_from: str = field(default_factory=lambda: _env("SMTP_FROM"))

    notes_dir: str = field(default_factory=lambda: _env("NOTES_DIR", "notes_pdfs"))


settings = Settings()
