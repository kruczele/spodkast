"""
Podcast synthesis API router.
Provides the /synthesize endpoint for article-to-podcast conversion.
"""

import os
import uuid
import tempfile
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Form, HTTPException, UploadFile, File, status
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.tts import synthesize_text
from app.audio_mixer import mix_podcast


router = APIRouter(prefix="/podcast", tags=["podcast"])

settings = get_settings()


# ──────────────────────────────────────────────────────────────────────────────
# Request / Response schemas
# ──────────────────────────────────────────────────────────────────────────────

class SynthesizeRequest(BaseModel):
    """JSON body for the /synthesize/json endpoint."""

    text: str = Field(
        ...,
        min_length=10,
        max_length=50_000,
        description="Article text to convert to speech (10–50 000 chars).",
    )
    language: str = Field(
        default="en",
        description="Language code: 'en' (English), 'pl' (Polish), 'es' (Spanish).",
    )
    voice_id: Optional[str] = Field(
        default=None,
        description="Override ElevenLabs voice ID. Leave empty to use the default for the selected language.",
    )
    include_intro: bool = Field(
        default=False,
        description="Prepend the default intro audio (audio/samples/intro.mp3) to the output.",
    )
    include_outro: bool = Field(
        default=False,
        description="Append the default outro audio (audio/samples/outro.mp3) to the output.",
    )

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        supported = get_settings().supported_languages
        v = v.lower().strip()
        if v not in supported:
            raise ValueError(
                f"Language '{v}' is not supported. Choose from: {supported}"
            )
        return v

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Text must not be empty or whitespace only.")
        return stripped


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

AUDIO_SAMPLES_DIR = Path("audio/samples")


def _resolve_sample(filename: str) -> Optional[Path]:
    """Return the path to a bundled audio sample if it exists, else None."""
    path = AUDIO_SAMPLES_DIR / filename
    return path if path.exists() else None


def _build_podcast(
    text: str,
    language: str,
    voice_id: Optional[str],
    include_intro: bool,
    include_outro: bool,
) -> bytes:
    """Core synthesis + mixing pipeline."""
    # Step 1: TTS synthesis
    narration = synthesize_text(text=text, language=language, voice_id=voice_id)

    # Step 2: Resolve optional intro / outro
    intro_path = _resolve_sample("intro.mp3") if include_intro else None
    outro_path = _resolve_sample("outro.mp3") if include_outro else None

    # Step 3: Mix audio
    mixed = mix_podcast(
        narration_bytes=narration,
        intro_path=intro_path,
        outro_path=outro_path,
    )
    return mixed


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/synthesize",
    summary="Synthesize article to podcast (JSON body)",
    response_class=Response,
    responses={
        200: {
            "content": {"audio/mpeg": {}},
            "description": "MP3 audio of the synthesized podcast.",
        }
    },
)
async def synthesize_json(request: SynthesizeRequest) -> Response:
    """
    Convert article text to a podcast-style MP3 using ElevenLabs TTS.

    - Supports English, Polish, and Spanish.
    - Optionally prepends/appends bundled intro/outro audio.
    - Voice is tuned for calm, soothing narration (goodnight read style).
    """
    request_id = uuid.uuid4().hex[:8]
    logger.info(
        f"[{request_id}] Synthesize request | lang={request.language} | "
        f"chars={len(request.text)} | intro={request.include_intro} | outro={request.include_outro}"
    )

    try:
        audio_bytes = _build_podcast(
            text=request.text,
            language=request.language,
            voice_id=request.voice_id,
            include_intro=request.include_intro,
            include_outro=request.include_outro,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except RuntimeError as e:
        logger.error(f"[{request_id}] Synthesis error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TTS synthesis failed: {e}",
        )
    except Exception as e:
        logger.exception(f"[{request_id}] Unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during audio generation.",
        )

    logger.info(f"[{request_id}] Returning {len(audio_bytes)} bytes of audio")
    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'attachment; filename="podcast_{request_id}.mp3"',
            "X-Request-Id": request_id,
        },
    )


@router.post(
    "/synthesize/form",
    summary="Synthesize article to podcast (form-data, with optional custom intro/outro upload)",
    response_class=Response,
    responses={
        200: {
            "content": {"audio/mpeg": {}},
            "description": "MP3 audio of the synthesized podcast.",
        }
    },
)
async def synthesize_form(
    text: Annotated[str, Form(min_length=10, max_length=50_000)],
    language: Annotated[str, Form()] = "en",
    voice_id: Annotated[Optional[str], Form()] = None,
    intro_file: Annotated[Optional[UploadFile], File()] = None,
    outro_file: Annotated[Optional[UploadFile], File()] = None,
) -> Response:
    """
    Form-data variant of the synthesis endpoint.
    Allows uploading custom intro/outro audio files (MP3/WAV/OGG).
    """
    request_id = uuid.uuid4().hex[:8]
    language = language.lower().strip()
    supported = settings.supported_languages
    if language not in supported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Language '{language}' not supported. Choose from: {supported}",
        )

    logger.info(
        f"[{request_id}] Form synthesize | lang={language} | chars={len(text)} | "
        f"custom_intro={intro_file is not None} | custom_outro={outro_file is not None}"
    )

    # Save uploaded files to temp paths
    tmp_intro_path = None
    tmp_outro_path = None

    try:
        if intro_file:
            tmp_intro = tempfile.NamedTemporaryFile(
                delete=False, suffix=Path(intro_file.filename or "intro.mp3").suffix
            )
            tmp_intro.write(await intro_file.read())
            tmp_intro.flush()
            tmp_intro_path = tmp_intro.name
            tmp_intro.close()

        if outro_file:
            tmp_outro = tempfile.NamedTemporaryFile(
                delete=False, suffix=Path(outro_file.filename or "outro.mp3").suffix
            )
            tmp_outro.write(await outro_file.read())
            tmp_outro.flush()
            tmp_outro_path = tmp_outro.name
            tmp_outro.close()

        # Synthesize narration
        narration = synthesize_text(
            text=text.strip(), language=language, voice_id=voice_id or None
        )

        # Resolve intro/outro: prefer uploaded files, then bundled samples
        intro_path = tmp_intro_path or _resolve_sample("intro.mp3")
        outro_path = tmp_outro_path or _resolve_sample("outro.mp3")

        audio_bytes = mix_podcast(
            narration_bytes=narration,
            intro_path=intro_path,
            outro_path=outro_path,
        )

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        logger.error(f"[{request_id}] TTS error: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception(f"[{request_id}] Unexpected: {e}")
        raise HTTPException(status_code=500, detail="Internal server error.")
    finally:
        # Clean up temp files
        for p in (tmp_intro_path, tmp_outro_path):
            if p and os.path.exists(p):
                os.unlink(p)

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'attachment; filename="podcast_{request_id}.mp3"',
            "X-Request-Id": request_id,
        },
    )


@router.get("/languages", summary="List supported languages")
async def list_languages() -> dict:
    """Return the list of supported language codes and their voice IDs."""
    s = get_settings()
    return {
        "supported_languages": s.supported_languages,
        "voice_map": s.voice_map,
        "model": s.elevenlabs_model_id,
    }
