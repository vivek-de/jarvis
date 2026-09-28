"""Pure memory logic — importance scoring, command parsing, dedupe. No DB needed."""
from backend.memory.commands import parse_command
from backend.memory.dedupe import cosine_similarity, is_duplicate
from backend.memory.importance import score_for


# ── importance ────────────────────────────────────────────────────────────────
def test_importance_scores():
    assert score_for("correction") == 0.95
    assert score_for("preference") == 0.9
    assert score_for("deadline") == 0.9
    assert score_for("decision") == 0.85
    assert score_for("trading_discipline") == 0.85
    assert score_for("project") == 0.8
    assert score_for("chatter") == 0.1
    assert score_for("unknown-cat") == 0.5           # default
    assert score_for("preference", override=1.7) == 1.0   # clamped


# ── commands ──────────────────────────────────────────────────────────────────
def test_parse_remember():
    c = parse_command("remember that I trade NIFTY weekly options")
    assert c and c.kind == "remember" and "NIFTY" in c.arg


def test_parse_recall():
    c = parse_command("what do you know about OptionIQ?")
    assert c and c.kind == "recall" and c.arg.lower() == "optioniq"


def test_parse_forget_vs_delete_ordering():
    c = parse_command("delete everything about EcoCycle")
    assert c and c.kind == "delete" and c.arg == "EcoCycle"      # not mis-parsed as forget
    c2 = parse_command("forget my old broker login note")
    assert c2 and c2.kind == "forget"


def test_non_command_is_none():
    assert parse_command("how's the market looking?") is None
    assert parse_command("summarize my week") is None


# ── dedupe ────────────────────────────────────────────────────────────────────
def test_is_duplicate_threshold():
    assert is_duplicate(0.95, 0.92) is True
    assert is_duplicate(0.90, 0.92) is False
    assert is_duplicate(None, 0.92) is False


def test_cosine_similarity():
    assert abs(cosine_similarity([1, 0, 0], [1, 0, 0]) - 1.0) < 1e-9
    assert abs(cosine_similarity([1, 0], [0, 1])) < 1e-9
