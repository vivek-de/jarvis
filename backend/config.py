"""
backend/config.py — 12-factor configuration for JARVIS (Phase 1).
═══════════════════════════════════════════════════════════════════════════════
All settings come from environment / .env with typed validation (pydantic-settings).
Nothing secret is hard-coded. The whole system has safe defaults so it runs on
Ollama alone with an empty .env.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# project root = jarvis/  (this file is jarvis/backend/config.py)
ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_prefix="JARVIS_",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_host: str = "127.0.0.1"
    app_port: int = 8100
    log_level: str = "INFO"
    env: str = "dev"
    version: str = "0.1.0"

    # ── Database (SQLite = conversation sessions, Phase 1+) ──────────────────
    db_path: str = "data/jarvis.db"

    # ── Long-term memory (Postgres + pgvector, Phase 3) ──────────────────────
    # Empty → long-term memory is disabled and JARVIS runs on SQLite sessions only.
    database_url: str = ""      # e.g. postgresql://mahavir@localhost:5432/jarvis
    embed_model: str = "nomic-embed-text"   # Ollama embedding model (768-dim)
    embed_dim: int = 768
    memory_dedupe_threshold: float = 0.92   # cosine sim ≥ this ⇒ update, not insert
    memory_retrieve_top_k: int = 5          # memories injected into context per turn

    # ── Local model (Ollama) ─────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # ── Model router task slots ("provider:model") ───────────────────────────
    model_general: str = "ollama:llama3.1:8b"
    model_fast: str = "ollama:llama3.1:8b"
    model_coding: str = "ollama:llama3.1:8b"
    model_reasoning: str = "ollama:llama3.1:8b"
    model_local: str = "ollama:llama3.1:8b"
    model_trading: str = "ollama:llama3.1:8b"

    # ── Cloud provider keys (optional, key-gated) ────────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # ── Spend cap ────────────────────────────────────────────────────────────
    daily_spend_cap_inr: float = 200.0
    usd_inr_rate: float = 88.0

    # ── Security ─────────────────────────────────────────────────────────────
    rate_limit_per_min: int = 60
    ssrf_allowlist: str = (
        "127.0.0.1:3001,localhost:3001,127.0.0.1:11434,localhost:11434"
    )

    # ── OptionIQ (read-only; Phase 13) ───────────────────────────────────────
    optioniq_base_url: str = "http://localhost:3001"

    # ── Use-case toggles (all off in Phase 1) ────────────────────────────────
    uc1_morning_brief: bool = False
    uc2_kite_token_guard: bool = False
    uc3_trade_journal_coach: bool = False
    uc4_placement_prep: bool = False
    uc5_project_memory: bool = False
    uc6_codebase_qa: bool = False
    uc7_market_alerts: bool = False
    uc8_weekly_review: bool = False

    # ── Channels (later phases) ──────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── derived helpers ──────────────────────────────────────────────────────
    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, v: str) -> str:
        return v.upper()

    @property
    def db_file(self) -> Path:
        p = Path(self.db_path)
        return p if p.is_absolute() else (ROOT / p)

    @property
    def ssrf_allowlist_set(self) -> set[str]:
        return {h.strip().lower() for h in self.ssrf_allowlist.split(",") if h.strip()}

    @property
    def task_slots(self) -> dict[str, str]:
        return {
            "GENERAL": self.model_general,
            "FAST": self.model_fast,
            "CODING": self.model_coding,
            "REASONING": self.model_reasoning,
            "LOCAL": self.model_local,
            "TRADING": self.model_trading,
        }

    def api_key_for(self, provider: str) -> str:
        return {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
        }.get(provider, "")

    def use_case_flags(self) -> dict[str, bool]:
        return {
            "UC1_morning_brief": self.uc1_morning_brief,
            "UC2_kite_token_guard": self.uc2_kite_token_guard,
            "UC3_trade_journal_coach": self.uc3_trade_journal_coach,
            "UC4_placement_prep": self.uc4_placement_prep,
            "UC5_project_memory": self.uc5_project_memory,
            "UC6_codebase_qa": self.uc6_codebase_qa,
            "UC7_market_alerts": self.uc7_market_alerts,
            "UC8_weekly_review": self.uc8_weekly_review,
        }


@lru_cache
def get_settings() -> Settings:
    """Cached singleton. Tests can clear via get_settings.cache_clear()."""
    return Settings()
