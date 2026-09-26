from backend.config import Settings


def test_defaults_are_local_and_safe():
    s = Settings(_env_file=None)
    assert set(s.task_slots) == {"GENERAL", "FAST", "CODING", "REASONING", "LOCAL", "TRADING"}
    assert all(v.startswith("ollama:") for v in s.task_slots.values())
    assert s.daily_spend_cap_inr == 200.0
    # all use cases OFF in Phase 1
    assert not any(s.use_case_flags().values())
    # no cloud keys by default
    assert s.api_key_for("anthropic") == ""


def test_env_override(monkeypatch):
    monkeypatch.setenv("JARVIS_DAILY_SPEND_CAP_INR", "50")
    monkeypatch.setenv("JARVIS_MODEL_CODING", "anthropic:claude-x")
    s = Settings(_env_file=None)
    assert s.daily_spend_cap_inr == 50.0
    assert s.task_slots["CODING"] == "anthropic:claude-x"


def test_ssrf_allowlist_parsed():
    s = Settings(_env_file=None)
    al = s.ssrf_allowlist_set
    assert "127.0.0.1:3001" in al        # OptionIQ
    assert "127.0.0.1:11434" in al       # Ollama
