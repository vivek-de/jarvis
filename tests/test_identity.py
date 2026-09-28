import getpass

from backend.identity.loader import build_system_prompt, identity_status


def test_prompt_includes_user_name_from_userdoc():
    p = build_system_prompt()
    assert "Vivek" in p                      # name comes from USER.md
    assert "JARVIS" in p
    # core boundaries present
    assert "read-only" in p.lower()
    assert "not trading advice" in p.lower() or "trading advice" in p.lower()


def test_name_not_derived_from_os_username():
    # whatever the OS login is, the prompt must not smuggle it in as the user's name
    os_user = getpass.getuser()
    p = build_system_prompt()
    # SOUL explicitly forbids OS-derived names; the only name present should be from USER.md
    if os_user.lower() not in ("vivek",):
        assert os_user not in p


def test_prompt_is_size_bounded():
    p = build_system_prompt()
    assert 0 < len(p) <= 8000 + 32           # MAX_PROMPT_CHARS + truncation marker slack


def test_channel_formatting_hint():
    cli = build_system_prompt(channel="cli")
    web = build_system_prompt(channel="web")
    tg = build_system_prompt(channel="telegram")
    assert "PLAIN TEXT" in cli and "no **bold**" in cli.lower() or "plain text" in cli.lower()
    assert "PLAIN TEXT" in tg
    assert "PLAIN TEXT" not in web        # web allows markdown


def test_grounding_rule_present():
    p = build_system_prompt()
    assert "i don't have that on file" in p.lower()


def test_identity_status_reports_files():
    st = identity_status()
    assert st["files"]["SOUL.md"] is True
    assert st["files"]["USER.md"] is True
    assert st["prompt_chars"] > 0
