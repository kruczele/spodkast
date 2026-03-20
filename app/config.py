"""
Configuration management for Spodkast service.
Loads settings from environment variables / .env file.

pydantic-settings v2 note:
  Field names are matched to env vars by converting to uppercase automatically.
  The deprecated `Field(env=...)` kwarg from v1 is NOT used here.
  Fields are named to match their env var counterparts (lowercase field -> UPPERCASE env var).
"""

from pydantic_settings import BaseSettings
from typing import Dict
from functools import lru_cache


class Settings(BaseSettings):
    # ElevenLabs API
    # Env var: ELEVENLABS_API_KEY (required — no default)
    elevenlabs_api_key: str

    # Env var: ELEVENLABS_MODEL_ID
    elevenlabs_model_id: str = "eleven_multilingual_v2"

    # Voice IDs per language
    # Env var: VOICE_ID_EN — Rachel: calm, warm English voice
    voice_id_en: str = "21m00Tcm4TlvDq8ikWAM"

    # Env var: VOICE_ID_PL — Polish (multilingual model)
    voice_id_pl: str = "21m00Tcm4TlvDq8ikWAM"

    # Env var: VOICE_ID_ES — Spanish (multilingual model)
    voice_id_es: str = "21m00Tcm4TlvDq8ikWAM"

    # Audio settings
    # Env var: AUDIO_OUTPUT_FORMAT
    audio_output_format: str = "mp3_44100_128"

    # Env var: OUTPUT_DIR
    output_dir: str = "./output"

    # Service settings
    # Env var: HOST
    host: str = "0.0.0.0"

    # Env var: PORT
    port: int = 8000

    # Env var: LOG_LEVEL
    log_level: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # Match UPPER_CASE env vars to lower_case field names
        "case_sensitive": False,
    }

    @property
    def voice_map(self) -> Dict[str, str]:
        """Return a mapping of language code -> ElevenLabs voice ID."""
        return {
            "en": self.voice_id_en,
            "pl": self.voice_id_pl,
            "es": self.voice_id_es,
        }

    @property
    def supported_languages(self) -> list[str]:
        return list(self.voice_map.keys())


@lru_cache()
def get_settings() -> Settings:
    return Settings()
