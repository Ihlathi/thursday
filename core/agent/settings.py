"""Provider credentials and runtime options, owned by Core alone.

The UI process is started without provider credentials on purpose. It may ask
Core to store a key and may ask whether one is stored, but the value never
travels back out of this process. Everything is written to a single JSON file
under AGENT_DATA_DIR with owner-only permissions where the platform supports
them.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock

# name -> (environment variable, secret?)
FIELDS: dict[str, tuple[str, bool]] = {
    'gemini_api_key': ('GEMINI_API_KEY', True),
    'gemini_model': ('GEMINI_MODEL', False),
    'elevenlabs_api_key': ('ELEVENLABS_API_KEY', True),
    'elevenlabs_voice_id': ('ELEVENLABS_VOICE_ID', False),
    'elevenlabs_stt_model': ('ELEVENLABS_STT_MODEL', False),
    'elevenlabs_tts_model': ('ELEVENLABS_TTS_MODEL', False),
}
MODEL_MODES = ('mock', 'gemini')
MAX_VALUE = 512


class Settings:
    """Stored values take priority over the environment Core was started with."""

    def __init__(self, path, default_mode='gemini'):
        self.path = Path(path)
        self.default_mode = default_mode if default_mode in MODEL_MODES else 'gemini'
        self._lock = RLock()
        self._values: dict[str, str] = {}
        self._mode: str | None = None
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        stored = raw.get('values')
        if isinstance(stored, dict):
            self._values = {
                name: value for name, value in stored.items()
                if name in FIELDS and isinstance(value, str) and len(value) <= MAX_VALUE
            }
        if raw.get('model_mode') in MODEL_MODES:
            self._mode = raw['model_mode']

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({'version': 1, 'model_mode': self._mode, 'values': self._values}, indent=1)
        handle, temporary = tempfile.mkstemp(dir=str(self.path.parent), prefix='.settings-')
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                stream.write(body)
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def value(self, name: str) -> str:
        """Stored value, else the environment Core inherited, else empty."""
        with self._lock:
            stored = self._values.get(name)
        if stored:
            return stored
        variable = FIELDS.get(name, (None, False))[0]
        return os.getenv(variable, '') if variable else ''

    def environment_value(self, name: str) -> str:
        variable = FIELDS.get(name, (None, False))[0]
        return os.getenv(variable, '') if variable else ''

    @property
    def model_mode(self) -> str:
        """'gemini' only when a key is actually available; never guesses."""
        with self._lock:
            chosen = self._mode or self.default_mode
        if chosen == 'gemini' and not self.value('gemini_api_key'):
            return 'mock'
        return chosen

    @property
    def requested_mode(self) -> str:
        with self._lock:
            return self._mode or self.default_mode

    def update(self, changes: dict) -> None:
        """Apply a partial update. '' clears a field back to the environment."""
        with self._lock:
            for name, value in changes.items():
                if name == 'model_mode':
                    if value in MODEL_MODES:
                        self._mode = value
                    continue
                if name not in FIELDS or not isinstance(value, str):
                    continue
                value = value.strip()
                if len(value) > MAX_VALUE:
                    raise ValueError(f'{name} is longer than {MAX_VALUE} characters')
                if value:
                    self._values[name] = value
                else:
                    self._values.pop(name, None)
            self._write()

    def clear(self) -> None:
        with self._lock:
            self._values = {}
            self._mode = None
            self._write()

    def state(self) -> dict:
        """What the UI is allowed to see: presence for secrets, value otherwise."""
        state = {'model_mode': self.model_mode, 'requested_mode': self.requested_mode}
        for name, (_, secret) in FIELDS.items():
            if secret:
                state[name + '_set'] = bool(self.value(name))
                state[name + '_from_environment'] = bool(
                    self.environment_value(name) and name not in self._values
                )
            else:
                state[name] = self.value(name)
        return state
