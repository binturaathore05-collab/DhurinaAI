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

    # Razorpay (keys of the teacher's merchant account; Durina is a Route linked account)
    razorpay_key_id: str = field(default_factory=lambda: _env("RAZORPAY_KEY_ID"))
    razorpay_key_secret: str = field(default_factory=lambda: _env("RAZORPAY_KEY_SECRET"))
    razorpay_webhook_secret: str = field(default_factory=lambda: _env("RAZORPAY_WEBHOOK_SECRET"))
    platform_linked_account: str = field(default_factory=lambda: _env("PLATFORM_LINKED_ACCOUNT"))
    platform_commission_percent: float = field(default_factory=lambda: float(_env("PLATFORM_COMMISSION_PERCENT", "20")))

    # SMS provider for OTP (plug in MSG91 / Twilio / etc. in services/sms.py)
    sms_provider: str = field(default_factory=lambda: _env("SMS_PROVIDER", "console"))

    notes_dir: str = field(default_factory=lambda: _env("NOTES_DIR", "notes_pdfs"))


settings = Settings()
