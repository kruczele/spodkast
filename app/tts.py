"""
ElevenLabs TTS integration for Spodkast.
Handles text-to-speech synthesis with calm, soothing "goodnight read" voice settings.
"""

import io
from typing import Optional
from loguru import logger
from elevenlabs import ElevenLabs
from elevenlabs.types import VoiceSettings

from app.config import get_settings


# Voice settings tuned for calm, soothing narration
# - Stability: high (0.8) → consistent, steady delivery
# - Similarity Boost: moderate (0.75) → natural sound
# - Style: low (0.1) → minimal expressiveness, calm tone
# - Speaker Boost: False → keeps the voice gentle, not projected
CALM_VOICE_SETTINGS = VoiceSettings(
    stability=0.80,
    similarity_boost=0.75,
    style=0.10,
    use_speaker_boost=False,
)


def get_tts_client() -> ElevenLabs:
    """Create and return an ElevenLabs client."""
    settings = get_settings()
    return ElevenLabs(api_key=settings.elevenlabs_api_key)


def synthesize_text(
    text: str,
    language: str,
    voice_id: Optional[str] = None,
) -> bytes:
    """
    Synthesize text to speech using ElevenLabs.

    Args:
        text: The article text to convert to speech.
        language: Language code (e.g., 'en', 'pl', 'es').
        voice_id: Override the default voice ID for this language.

    Returns:
        Raw audio bytes (MP3 format).

    Raises:
        ValueError: If the language is not supported.
        RuntimeError: If TTS synthesis fails.
    """
    settings = get_settings()

    # Resolve voice ID
    if voice_id is None:
        if language not in settings.voice_map:
            raise ValueError(
                f"Unsupported language: '{language}'. "
                f"Supported: {settings.supported_languages}"
            )
        voice_id = settings.voice_map[language]

    logger.info(
        f"Synthesizing {len(text)} chars | lang={language} | "
        f"voice={voice_id} | model={settings.elevenlabs_model_id}"
    )

    client = get_tts_client()

    try:
        audio_generator = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=settings.elevenlabs_model_id,
            voice_settings=CALM_VOICE_SETTINGS,
            output_format=settings.audio_output_format,
        )

        # Collect generator chunks into bytes
        audio_bytes = b"".join(audio_generator)
        logger.info(f"Synthesis complete: {len(audio_bytes)} bytes")
        return audio_bytes

    except Exception as e:
        logger.error(f"ElevenLabs TTS failed: {e}")
        raise RuntimeError(f"Speech synthesis failed: {e}") from e
