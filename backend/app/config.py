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
    public_base_url: str = field(default_factory=lambda: _env("PUBLIC_BASE_URL"))

    # Set TRUST_PROXY=1 only when the API runs behind our own proxy / load balancer (then the student's IP is
    # read from X-Forwarded-For for the OTP-per-IP limit). Off by default, because the header can be faked.
    trust_proxy: bool = field(default_factory=lambda: _env("TRUST_PROXY", "0") == "1")

    notes_dir: str = field(default_factory=lambda: _env("NOTES_DIR", "notes_pdfs"))


settings = Settings()
