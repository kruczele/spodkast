"""
ElevenLabs TTS integration for Spodkast.
Handles text-to-speech synthesis with calm, soothing "goodnight read" voice settings.
"""

from typing import Optional
from loguru import logger
from elevenlabs import ElevenLabs
from elevenlabs.types import VoiceSettings

from app.config import get_settings


def get_tts_client() -> ElevenLabs:
    settings = get_settings()
    return ElevenLabs(api_key=settings.elevenlabs_api_key, timeout=settings.tts_timeout_seconds)


def synthesize_text(
    text: str,
    language: str,
    voice_id: Optional[str] = None,
    speed: float = 1.0,
    stability: float = 0.80,
    similarity_boost: float = 0.75,
    style: float = 0.10,
    use_speaker_boost: bool = False,
) -> bytes:
    """
    Synthesize text to speech using ElevenLabs.

    Returns raw audio bytes (MP3 format).
    Raises ValueError for unsupported language, RuntimeError on TTS failure.
    """
    settings = get_settings()

    # Fix: use `not voice_id` so empty string also falls back to default
    if not voice_id:
        if language not in settings.voice_map:
            raise ValueError(
                f"Unsupported language: '{language}'. "
                f"Supported: {settings.supported_languages}"
            )
        voice_id = settings.voice_map[language]

    logger.info(
        f"Synthesizing {len(text)} chars | lang={language} | voice={voice_id} | "
        f"speed={speed} | stability={stability} | model={settings.elevenlabs_model_id}"
    )

    client = get_tts_client()
    voice_settings = VoiceSettings(
        stability=stability,
        similarity_boost=similarity_boost,
        style=style,
        use_speaker_boost=use_speaker_boost,
        speed=speed,
    )

    try:
        audio_generator = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=settings.elevenlabs_model_id,
            voice_settings=voice_settings,
            output_format=settings.audio_output_format,
        )
        audio_bytes = b"".join(audio_generator)
        logger.info(f"Synthesis complete: {len(audio_bytes)} bytes")
        return audio_bytes

    except Exception as e:
        logger.error(f"ElevenLabs TTS failed: {e}")
        raise RuntimeError(f"Speech synthesis failed: {e}") from e
