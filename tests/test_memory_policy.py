from backend.memory.policy import CATEGORIES, should_remember


def test_secrets_never_remembered():
    d = should_remember("my zerodha password is hunter2")
    assert d.remember is False
    d = should_remember("API_KEY=sk-abc123 store this please")
    assert d.remember is False


def test_explicit_remember():
    d = should_remember("remember that I prefer replies under 5 lines")
    assert d.remember is True
    assert d.category in CATEGORIES


def test_preference_detected():
    d = should_remember("Always use IST and never send notifications at night")
    assert d.remember is True and d.category == "preference"


def test_decision_detected():
    d = should_remember("I decided to keep the Momentum Basket on paper until mid-October")
    assert d.remember is True and d.category == "decision"


def test_deadline_detected():
    d = should_remember("Amazon SDE-1 OA is on the 12th")
    assert d.remember is True and d.category == "deadline"


def test_project_status_detected():
    d = should_remember("MarketGPT is built but the write-up is pending")
    assert d.remember is True and d.category == "project"


def test_questions_not_remembered():
    assert should_remember("what did I decide about OptionIQ?").remember is False
    assert should_remember("how does the momentum screener work?").remember is False


def test_chatter_not_remembered():
    assert should_remember("ok cool thanks").remember is False
    assert should_remember("hmm let me think").remember is False


def test_correction_supersedes():
    d = should_remember("actually, the review is mid-November not mid-October")
    assert d.remember is True and d.category == "correction" and d.importance == 5
