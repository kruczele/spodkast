"""
Unit tests for voice selection and persistence in Spodkast.

Tests cover:
1. TTS synthesize_text correctly uses caller-supplied voice_id instead of default
2. Backend SynthesisParams properly propagates voice_id through the pipeline
3. The /podcast/synthesize endpoint accepts and uses an explicit voice_id
4. The voice_id=None / empty-string fallback to the language-default voice
"""

from unittest.mock import MagicMock, patch, call
import pytest

from app.tts import synthesize_text
from app.config import get_settings
from app.routers.podcast import SynthesisParams


# ── Helpers ──────────────────────────────────────────────────────────────────

NICOLE_VOICE_ID = "piTKgcLEGmPE4e6mEKli"
GRACE_VOICE_ID  = "oWAxZDx7w5VEj9dCyTzz"


def _fake_audio_generator(chunks=None):
    """Return an iterable that mimics the ElevenLabs generator."""
    if chunks is None:
        chunks = [b"fake_audio_data"]
    return iter(chunks)


# ── TTS: voice_id pass-through ────────────────────────────────────────────────

class TestSynthesizeTextVoiceId:
    """synthesize_text must pass the caller-supplied voice_id to ElevenLabs."""

    def test_explicit_voice_id_is_used(self, monkeypatch):
        """When a voice_id is provided, it should reach the ElevenLabs API call."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        get_settings.cache_clear()

        captured_voice_id = None

        def fake_convert(**kwargs):
            nonlocal captured_voice_id
            captured_voice_id = kwargs.get("voice_id")
            return _fake_audio_generator()

        with patch("app.tts.ElevenLabs") as MockEL:
            instance = MockEL.return_value
            instance.text_to_speech.convert.side_effect = fake_convert

            synthesize_text(
                text="Hello, this is a test narration with enough words.",
                language="en",
                voice_id=GRACE_VOICE_ID,
            )

        assert captured_voice_id == GRACE_VOICE_ID, (
            f"Expected voice_id={GRACE_VOICE_ID!r} to be passed to ElevenLabs, "
            f"but got {captured_voice_id!r}"
        )

    def test_none_voice_id_falls_back_to_language_default(self, monkeypatch):
        """When voice_id is None, the language default from settings must be used."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        monkeypatch.setenv("VOICE_ID_EN", NICOLE_VOICE_ID)
        get_settings.cache_clear()

        captured_voice_id = None

        def fake_convert(**kwargs):
            nonlocal captured_voice_id
            captured_voice_id = kwargs.get("voice_id")
            return _fake_audio_generator()

        with patch("app.tts.ElevenLabs") as MockEL:
            instance = MockEL.return_value
            instance.text_to_speech.convert.side_effect = fake_convert

            synthesize_text(
                text="Hello, this is a test narration with enough words.",
                language="en",
                voice_id=None,
            )

        assert captured_voice_id == NICOLE_VOICE_ID, (
            f"Expected language default voice {NICOLE_VOICE_ID!r} when voice_id=None, "
            f"but got {captured_voice_id!r}"
        )

    def test_empty_string_voice_id_falls_back_to_language_default(self, monkeypatch):
        """An empty-string voice_id (from the frontend's default option) must also fall back."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        monkeypatch.setenv("VOICE_ID_EN", NICOLE_VOICE_ID)
        get_settings.cache_clear()

        captured_voice_id = None

        def fake_convert(**kwargs):
            nonlocal captured_voice_id
            captured_voice_id = kwargs.get("voice_id")
            return _fake_audio_generator()

        with patch("app.tts.ElevenLabs") as MockEL:
            instance = MockEL.return_value
            instance.text_to_speech.convert.side_effect = fake_convert

            synthesize_text(
                text="Hello, this is a test narration with enough words.",
                language="en",
                voice_id="",   # empty string — same as frontend default option value=""
            )

        assert captured_voice_id == NICOLE_VOICE_ID, (
            f"Expected language default voice {NICOLE_VOICE_ID!r} when voice_id='', "
            f"but got {captured_voice_id!r}"
        )

    def test_different_voice_replaces_default(self, monkeypatch):
        """Selecting a different voice in the UI must override the per-language default."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        monkeypatch.setenv("VOICE_ID_EN", NICOLE_VOICE_ID)  # default is Nicole
        get_settings.cache_clear()

        captured_voice_id = None

        def fake_convert(**kwargs):
            nonlocal captured_voice_id
            captured_voice_id = kwargs.get("voice_id")
            return _fake_audio_generator()

        with patch("app.tts.ElevenLabs") as MockEL:
            instance = MockEL.return_value
            instance.text_to_speech.convert.side_effect = fake_convert

            # User selected Grace instead of the default Nicole
            synthesize_text(
                text="Hello, this is a test narration with enough words.",
                language="en",
                voice_id=GRACE_VOICE_ID,
            )

        assert captured_voice_id == GRACE_VOICE_ID, (
            f"Selected voice {GRACE_VOICE_ID!r} should override the default "
            f"{NICOLE_VOICE_ID!r}, but got {captured_voice_id!r}"
        )
        assert captured_voice_id != NICOLE_VOICE_ID, (
            "Janet/Nicole (the default) should NOT be used when a different voice is selected"
        )


# ── SynthesisParams model ─────────────────────────────────────────────────────

class TestSynthesisParamsVoiceId:
    """SynthesisParams must correctly handle all voice_id input variations."""

    def test_none_voice_id_allowed(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        get_settings.cache_clear()
        params = SynthesisParams(language="en", voice_id=None)
        assert params.voice_id is None

    def test_explicit_voice_id_preserved(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        get_settings.cache_clear()
        params = SynthesisParams(language="en", voice_id=GRACE_VOICE_ID)
        assert params.voice_id == GRACE_VOICE_ID

    def test_empty_string_voice_id_allowed(self, monkeypatch):
        """Empty string from the UI default option must be accepted by the model."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        get_settings.cache_clear()
        params = SynthesisParams(language="en", voice_id="")
        assert params.voice_id == ""

    def test_voice_id_not_stripped_to_wrong_value(self, monkeypatch):
        """A valid voice ID must not be altered by the model."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        get_settings.cache_clear()
        params = SynthesisParams(language="en", voice_id=NICOLE_VOICE_ID)
        assert params.voice_id == NICOLE_VOICE_ID

    def test_default_voice_id_is_none(self, monkeypatch):
        """When voice_id is omitted, it must default to None (not a hardcoded string)."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        get_settings.cache_clear()
        params = SynthesisParams(language="en")
        assert params.voice_id is None, (
            "Default voice_id must be None so the backend picks up the per-language default "
            "from settings, not a hardcoded value"
        )


# ── Config: voice_map ─────────────────────────────────────────────────────────

class TestConfigVoiceMap:
    """Settings.voice_map must correctly map language codes to voice IDs."""

    def test_voice_map_returns_configured_voice_ids(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        monkeypatch.setenv("VOICE_ID_EN", GRACE_VOICE_ID)
        monkeypatch.setenv("VOICE_ID_PL", NICOLE_VOICE_ID)
        get_settings.cache_clear()

        settings = get_settings()
        assert settings.voice_map["en"] == GRACE_VOICE_ID
        assert settings.voice_map["pl"] == NICOLE_VOICE_ID

    def test_voice_map_supports_all_languages(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        get_settings.cache_clear()

        settings = get_settings()
        for lang in settings.supported_languages:
            assert lang in settings.voice_map, f"Language '{lang}' missing from voice_map"
            assert settings.voice_map[lang], f"voice_map['{lang}'] must not be empty"

    def test_unsupported_language_raises_when_no_voice_id(self, monkeypatch):
        """synthesize_text must raise ValueError for an unknown language with no voice_id."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="Unsupported language"):
            synthesize_text(
                text="Hello, this is a test narration with enough words.",
                language="xx",   # unsupported language code
                voice_id=None,   # no override → must look up from voice_map → raises
            )


# ── Integration: voice_id flows end-to-end through _build_podcast ─────────────

class TestVoiceIdEndToEnd:
    """The voice_id must flow from the API layer all the way to ElevenLabs convert()."""

    def test_synthesize_json_passes_voice_id_to_elevenlabs(self, monkeypatch):
        """
        Posting to /podcast/synthesize with an explicit voice_id must reach ElevenLabs.
        This test verifies there are no 'black holes' in the call chain that swallow
        the voice_id and substitute the default.
        """
        import httpx
        from fastapi.testclient import TestClient
        from app.main import app

        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        monkeypatch.setenv("VOICE_ID_EN", NICOLE_VOICE_ID)  # default is Nicole
        get_settings.cache_clear()

        captured_voice_id = None

        def fake_convert(**kwargs):
            nonlocal captured_voice_id
            captured_voice_id = kwargs.get("voice_id")
            return _fake_audio_generator([b"fake_mp3_data_for_testing_purposes"])

        with patch("app.tts.ElevenLabs") as MockEL:
            instance = MockEL.return_value
            instance.text_to_speech.convert.side_effect = fake_convert

            client = TestClient(app)
            response = client.post(
                "/podcast/synthesize",
                json={
                    "text": "This is a test article with more than ten characters.",
                    "language": "en",
                    "voice_id": GRACE_VOICE_ID,   # user selected Grace
                },
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        assert captured_voice_id == GRACE_VOICE_ID, (
            f"Grace ({GRACE_VOICE_ID}) should have been used but ElevenLabs received {captured_voice_id!r}. "
            f"Voice selection is broken — the chosen voice is being ignored."
        )
        assert captured_voice_id != NICOLE_VOICE_ID, (
            "Nicole (the default) should NOT be used when Grace was explicitly selected"
        )

    def test_synthesize_json_uses_default_when_voice_id_omitted(self, monkeypatch):
        """Omitting voice_id must fall back to the language default (Nicole for EN)."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        monkeypatch.setenv("VOICE_ID_EN", NICOLE_VOICE_ID)
        get_settings.cache_clear()

        captured_voice_id = None

        def fake_convert(**kwargs):
            nonlocal captured_voice_id
            captured_voice_id = kwargs.get("voice_id")
            return _fake_audio_generator([b"fake_mp3_data_for_testing_purposes"])

        with patch("app.tts.ElevenLabs") as MockEL:
            instance = MockEL.return_value
            instance.text_to_speech.convert.side_effect = fake_convert

            from fastapi.testclient import TestClient
            from app.main import app
            client = TestClient(app)
            response = client.post(
                "/podcast/synthesize",
                json={
                    "text": "This is a test article with more than ten characters.",
                    "language": "en",
                    # voice_id intentionally omitted → should use language default
                },
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        assert captured_voice_id == NICOLE_VOICE_ID, (
            f"Expected default voice {NICOLE_VOICE_ID!r} when voice_id is omitted, "
            f"got {captured_voice_id!r}"
        )
