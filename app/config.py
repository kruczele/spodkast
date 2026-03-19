"""
Configuration management for Spodkast service.
Loads settings from environment variables / .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Dict
from functools import lru_cache


class Settings(BaseSettings):
    # ElevenLabs API
    elevenlabs_api_key: str = Field(..., env="ELEVENLABS_API_KEY")
    elevenlabs_model_id: str = Field(
        default="eleven_multilingual_v2", env="ELEVENLABS_MODEL_ID"
    )

    # Voice IDs per language
    voice_id_en: str = Field(
        default="21m00Tcm4TlvDq8ikWAM", env="VOICE_ID_EN"
    )  # Rachel - calm, warm English voice
    voice_id_pl: str = Field(
        default="21m00Tcm4TlvDq8ikWAM", env="VOICE_ID_PL"
    )  # Polish (multilingual model)
    voice_id_es: str = Field(
        default="21m00Tcm4TlvDq8ikWAM", env="VOICE_ID_ES"
    )  # Spanish (multilingual model)

    # Audio settings
    audio_output_format: str = Field(
        default="mp3_44100_128", env="AUDIO_OUTPUT_FORMAT"
    )
    output_dir: str = Field(default="./output", env="OUTPUT_DIR")

    # Service
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

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
