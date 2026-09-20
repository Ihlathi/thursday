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
