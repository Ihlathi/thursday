from agent.desktop import PROVIDER_KEYS, child_environments


def test_desktop_launcher_distributes_only_required_credentials():
    base = {
        "PATH": "example",
        "AGENT_UI_TOKEN": "old-ui",
        "AGENT_PLATFORM_TOKEN": "old-platform",
        "GEMINI_API_KEY": "gemini-secret",
        "ELEVENLABS_API_KEY": "voice-secret",
        "ELEVENLABS_VOICE_ID": "voice-id",
    }

    core, platform, ui = child_environments(base, "new-ui", "new-platform", 9123)

    assert core["AGENT_UI_TOKEN"] == "new-ui"
    assert core["AGENT_PLATFORM_TOKEN"] == "new-platform"
    assert core["GEMINI_API_KEY"] == "gemini-secret"
    assert platform["AGENT_PLATFORM_TOKEN"] == "new-platform"
    assert "AGENT_UI_TOKEN" not in platform
    assert ui["AGENT_UI_TOKEN"] == "new-ui"
    assert "AGENT_PLATFORM_TOKEN" not in ui
    assert ui["AGENT_UI_URL"] == "ws://127.0.0.1:9123/v1/ui"
    for key in PROVIDER_KEYS:
        assert key not in platform
        assert key not in ui


def test_env_file_seeds_without_overriding_real_environment(tmp_path):
    from agent.desktop import load_env_file

    path = tmp_path / ".env"
    path.write_text(
        "# comment\n"
        "GEMINI_API_KEY=from-file\n"
        "ELEVENLABS_VOICE_ID=\n"
        "GEMINI_MODEL='quoted-model'\n"
        "junk line\n",
        encoding="utf-8",
    )
    base = {"GEMINI_API_KEY": "already-set"}
    loaded = load_env_file(path, base)

    assert base["GEMINI_API_KEY"] == "already-set"  # a real variable always wins
    assert base["GEMINI_MODEL"] == "quoted-model"
    assert "ELEVENLABS_VOICE_ID" not in base  # blank values are not seeded
    assert loaded == ["GEMINI_MODEL"]


def test_missing_env_file_is_not_an_error(tmp_path):
    from agent.desktop import load_env_file

    assert load_env_file(tmp_path / "nothing-here", {}) == []


def test_launcher_prefers_the_built_app_when_present(monkeypatch, tmp_path):
    from agent import desktop

    built = tmp_path / "jarvis.exe"
    monkeypatch.setattr(desktop, "RELEASE_UI", built)
    monkeypatch.setattr(desktop, "_package_manager", lambda: "npm")

    assert desktop.ui_command() == ["npm", "run", "tauri", "dev"]  # nothing built yet
    built.write_text("", encoding="utf-8")
    assert desktop.ui_command() == [str(built)]
    assert desktop.ui_command(force_dev=True) == ["npm", "run", "tauri", "dev"]
