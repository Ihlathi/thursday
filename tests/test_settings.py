"""Settings must persist, prefer stored values over the environment, and never
hand a secret back to the UI."""
import json

import pytest
from agent import providers
from agent.contracts import envelope, validate
from agent.server import CoreServer
from agent.settings import Settings
from agent.transport import client_connect

UI = 'ui-token-' + 'u' * 32
BRIDGE = 'bridge-token-' + 'b' * 32


def test_stored_value_beats_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'from-environment')
    settings = Settings(tmp_path / 'settings.json')
    assert settings.value('gemini_api_key') == 'from-environment'
    settings.update({'gemini_api_key': 'from-settings'})
    assert settings.value('gemini_api_key') == 'from-settings'
    # Reloading a fresh instance sees the same thing.
    assert Settings(tmp_path / 'settings.json').value('gemini_api_key') == 'from-settings'


def test_blank_clears_back_to_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'from-environment')
    settings = Settings(tmp_path / 'settings.json')
    settings.update({'gemini_api_key': 'typed'})
    settings.update({'gemini_api_key': ''})
    assert settings.value('gemini_api_key') == 'from-environment'


def test_state_reports_presence_not_secrets(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    settings = Settings(tmp_path / 'settings.json')
    settings.update({'gemini_api_key': 'super-secret', 'gemini_model': 'gemini-3.8-flash'})
    state = settings.state()
    assert state['gemini_api_key_set'] is True
    assert state['gemini_model'] == 'gemini-3.8-flash'
    assert 'super-secret' not in json.dumps(state)
    assert not any(key.endswith('api_key') for key in state)


def test_mode_never_claims_gemini_without_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    settings = Settings(tmp_path / 'settings.json', 'gemini')
    assert settings.model_mode == 'mock'
    assert settings.requested_mode == 'gemini'
    settings.update({'gemini_api_key': 'key'})
    assert settings.model_mode == 'gemini'


def test_oversized_value_is_rejected(tmp_path):
    settings = Settings(tmp_path / 'settings.json')
    with pytest.raises(ValueError):
        settings.update({'gemini_api_key': 'x' * 513})


def test_providers_read_the_installed_settings(tmp_path, monkeypatch):
    monkeypatch.delenv('ELEVENLABS_VOICE_ID', raising=False)
    settings = Settings(tmp_path / 'settings.json')
    settings.update({'elevenlabs_voice_id': 'voice-42'})
    monkeypatch.setattr(providers, 'ACTIVE', settings)
    assert providers.setting('elevenlabs_voice_id') == 'voice-42'
    monkeypatch.setattr(providers, 'ACTIVE', None)


async def _ui_socket(port):
    return await client_connect(f'ws://127.0.0.1:{port}/v1/ui', 'ui', UI)


async def _roundtrip(ws, message):
    await ws.send(json.dumps(message))
    return validate(json.loads(await ws.recv()))


async def test_settings_round_trip_over_the_socket(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    server = CoreServer(UI, BRIDGE, None, tmp_path, mode='gemini')
    port = await server.start(0)
    ws = await _ui_socket(port)
    try:
        state = await _roundtrip(ws, envelope('settings_get', {}))
        assert state['type'] == 'settings_state'
        assert state['payload']['gemini_api_key_set'] is False
        assert state['payload']['model_mode'] == 'mock'

        saved = await _roundtrip(ws, envelope('settings_update', {'gemini_api_key': 'live-key'}))
        assert saved['payload']['saved'] is True
        assert saved['payload']['gemini_api_key_set'] is True
        assert saved['payload']['model_mode'] == 'gemini'
        assert 'live-key' not in json.dumps(saved)
        # Core now builds a live provider without restarting.
        assert server.settings.value('gemini_api_key') == 'live-key'

        cleared = await _roundtrip(ws, envelope('settings_update', {'clear_all': True}))
        assert cleared['payload']['gemini_api_key_set'] is False
    finally:
        await ws.close()
        await server.close()
        providers.configure(None)
