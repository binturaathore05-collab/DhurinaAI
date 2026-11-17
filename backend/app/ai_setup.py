"""Builds the AI side of the backend: model router (A4), safety check (A2) and the AI teacher.

Used by the API and by the safety test lab (A8), so the tests run exactly the same pipeline as real students.
"""
from dataclasses import dataclass

from .db import Database
from .services import moderation, switches
from .services.knowledge import KnowledgeBase
from .services.llm import FakeLLM, OpenAICompatibleLLM
from .services.tutor import Tutor


@dataclass
class AI:
    raw_llm: switches.ModelRouter
    side_llm: switches.ModelRouter
    moderator: moderation.Moderator
    llm: moderation.ModeratedLLM
    tutor: Tutor
    provider: str
    main: str
    small: str
    backup: str


def resolve_provider(settings, override: str | None = None) -> str:
    p = override or settings.moderation_provider
    if p == "auto":
        p = "llm" if settings.llm_api_key else "rules"
    return p


def build(db: Database, settings, provider: str | None = None, switch_db: Database | None = None) -> AI:
    """switch_db: where the emergency switches are read (the live database); defaults to db."""
    sdb = switch_db or db

    def client(model: str, timeout: float = 60):
        if not settings.llm_api_key or not model:
            return None
        return OpenAICompatibleLLM(settings.llm_base_url, settings.llm_api_key, model, timeout)

    fake = None if settings.llm_api_key else FakeLLM()   # local development / tests without an AI key
    main, small, backup = settings.llm_model, settings.llm_small_model, settings.llm_backup_model
    # A4: every job goes to the first model in line that is not switched off in admin → Emergency
    raw_llm = switches.ModelRouter(sdb, [(main, client(main) or fake), (backup, client(backup))], track=True)
    # optional cheaper model for small helper jobs (search keywords, safety check); answers, notes and tests use the
    # main model. Search keywords are never shown to the student, so they skip the output check.
    side_llm = switches.ModelRouter(sdb, [(small, client(small)), (main, client(main) or fake), (backup, client(backup))])
    prov = resolve_provider(settings, provider)
    mod_model = small or main
    moderator = moderation.Moderator(
        db, prov,
        switches.ModelRouter(sdb, [(small, client(small, 12)), (main, client(main, 12) or FakeLLM()), (backup, client(backup, 12))]),
        settings.llm_base_url, settings.llm_api_key,
        model_name="omni-moderation-latest" if prov == "openai" else (mod_model if prov == "llm" else "rules"))
    llm = moderation.ModeratedLLM(raw_llm, moderator)
    return AI(raw_llm, side_llm, moderator, llm, Tutor(db, KnowledgeBase(db), llm, side_llm), prov, main, small, backup)
