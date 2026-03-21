"""
Podcast synthesis API router.
Provides the /synthesize endpoint for article-to-podcast conversion.
"""

import asyncio
import io
import os
import re
import uuid
import zipfile
import tempfile
from pathlib import Path
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile, File, status
from fastapi.responses import Response, StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field, field_validator

import anthropic as _anthropic
from app.config import get_settings
from app.tts import synthesize_text
from app.audio_mixer import mix_podcast
from app.script_generator import (
    generate_conspect, expand_episode, translate_script, localize_script,
    translate_and_localize, EXPAND_SYSTEM, LANGUAGE_NAMES,
    TRANSLATE_SYSTEM_TEMPLATE, LOCALIZE_SYSTEM_TEMPLATE,
)
from app import sessions, jobs
from app.jobs import JobStatus


router = APIRouter(prefix="/podcast", tags=["podcast"])


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


async def _resolve_source(source: str) -> str:
    """
    Resolve a source value to plain text.

    Accepted formats:
    - Raw text: returned as-is.
    - URL (http:// or https://): fetched; HTML tags stripped.
    - File path (/abs, ./rel, or ~/home): read from disk.
    """
    source = source.strip()

    # URL
    if source.startswith(("http://", "https://")):
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            try:
                resp = await client.get(source)
            except httpx.RequestError as e:
                raise ValueError(f"Failed to fetch URL: {e}")
        if resp.status_code >= 400:
            raise ValueError(f"URL returned HTTP {resp.status_code}")
        content = resp.text
        # Strip HTML tags for web pages
        if "text/html" in resp.headers.get("content-type", ""):
            content = re.sub(r"<[^>]+>", " ", content)
            content = re.sub(r"\s{2,}", " ", content).strip()
        return content

    # File path
    if source.startswith(("/", "./", "../", "~/")):
        path = Path(source).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"File not found: {path}")
        if not path.is_file():
            raise ValueError(f"Path is not a file: {path}")
        return path.read_text(encoding="utf-8", errors="replace")

    # Raw text
    return source


def _build_podcast(
    text: str,
    language: str,
    voice_id: Optional[str],
    include_intro: bool,
    include_outro: bool,
    speed: float = 1.0,
    stability: float = 0.80,
    similarity_boost: float = 0.75,
    style: float = 0.10,
    use_speaker_boost: bool = False,
) -> bytes:
    """Core synthesis + mixing pipeline."""
    # Step 1: TTS synthesis
    narration = synthesize_text(
        text=text, language=language, voice_id=voice_id,
        speed=speed, stability=stability, similarity_boost=similarity_boost,
        style=style, use_speaker_boost=use_speaker_boost,
    )

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
    supported = get_settings().supported_languages
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


class GenerateRequest(BaseModel):
    """JSON body for the /generate endpoint."""

    source: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description=(
            "Source material. Accepts: raw text, a URL (http/https), "
            "or a file path (/abs, ./rel, ~/home)."
        ),
    )
    language: str = Field(
        default="en",
        description="Language code: 'en' (English), 'pl' (Polish), 'es' (Spanish).",
    )
    voice_id: Optional[str] = Field(
        default=None,
        description="Override ElevenLabs voice ID.",
    )
    include_intro: bool = Field(default=False)
    include_outro: bool = Field(default=False)

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


@router.post(
    "/generate",
    summary="Generate up to 8 episodes from source material and synthesize to a ZIP of MP3s",
    response_class=Response,
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": (
                "ZIP archive containing one MP3 per generated episode. "
                "If the source material was insufficient for 8 episodes, "
                "the archive also contains operator_message.txt and the "
                "X-Operator-Message response header is set."
            ),
        }
    },
)
async def generate_and_synthesize(request: GenerateRequest) -> Response:
    """
    Two-step pipeline:
    1. Use Claude to transform raw source material into up to 8 sleep-friendly episode scripts.
       If the material doesn't support 8 full episodes, Claude stops early and includes an
       operator message requesting more data.
    2. Synthesize each script to audio via ElevenLabs TTS.
    3. Return all episodes as a ZIP archive (episode_01.mp3 … episode_N.mp3).

    Requires ANTHROPIC_API_KEY to be set in the environment.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY is not configured. Set it in your .env file.",
        )

    request_id = uuid.uuid4().hex[:8]
    logger.info(
        f"[{request_id}] Generate request | lang={request.language} | "
        f"source={request.source[:80]!r}"
    )

    try:
        source_text = await _resolve_source(request.source)
        logger.info(f"[{request_id}] Source resolved ({len(source_text)} chars)")

        result = generate_scripts(
            source_text=source_text,
            api_key=settings.anthropic_api_key,
        )
        if not result.episodes:
            raise RuntimeError("No episodes were generated from the provided source material.")

        logger.info(
            f"[{request_id}] {len(result.episodes)} episode(s) ready, synthesizing"
        )

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, script in enumerate(result.episodes, 1):
                logger.info(f"[{request_id}] Synthesizing episode {i}/{len(result.episodes)}")
                audio = _build_podcast(
                    text=script,
                    language=request.language,
                    voice_id=request.voice_id,
                    include_intro=request.include_intro,
                    include_outro=request.include_outro,
                )
                zf.writestr(f"episode_{i:02d}.mp3", audio)

            if result.operator_message:
                zf.writestr("operator_message.txt", result.operator_message)

        zip_bytes = zip_buffer.getvalue()

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except RuntimeError as e:
        logger.error(f"[{request_id}] Generation error: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        logger.exception(f"[{request_id}] Unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during podcast generation.",
        )

    response_headers = {
        "Content-Disposition": f'attachment; filename="podcast_{request_id}.zip"',
        "X-Request-Id": request_id,
        "X-Episode-Count": str(len(result.episodes)),
    }
    if result.operator_message:
        response_headers["X-Operator-Message"] = result.operator_message

    logger.info(
        f"[{request_id}] Returning ZIP with {len(result.episodes)} episode(s) "
        f"({len(zip_bytes)} bytes)"
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers=response_headers,
    )


@router.post(
    "/generate/form",
    summary="Generate episodes from an uploaded file and synthesize to a ZIP of MP3s",
    response_class=Response,
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "ZIP archive containing one MP3 per generated episode.",
        }
    },
)
async def generate_and_synthesize_form(
    source_file: Annotated[UploadFile, File(description="Source material as a text file (UTF-8).")],
    language: Annotated[str, Form()] = "en",
    voice_id: Annotated[Optional[str], Form()] = None,
    include_intro: Annotated[bool, Form()] = False,
    include_outro: Annotated[bool, Form()] = False,
) -> Response:
    """
    File-upload variant of /generate. Accepts a plain-text file as source material
    and returns a ZIP of synthesized episode MP3s.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY is not configured. Set it in your .env file.",
        )

    language = language.lower().strip()
    supported = get_settings().supported_languages
    if language not in supported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Language '{language}' not supported. Choose from: {supported}",
        )

    request_id = uuid.uuid4().hex[:8]
    raw_bytes = await source_file.read()
    source_text = raw_bytes.decode("utf-8", errors="replace")
    logger.info(
        f"[{request_id}] Generate/form request | lang={language} | "
        f"file={source_file.filename!r} | chars={len(source_text)}"
    )

    try:
        result = generate_scripts(source_text=source_text, api_key=settings.anthropic_api_key)
        if not result.episodes:
            raise RuntimeError("No episodes were generated from the provided source material.")

        logger.info(f"[{request_id}] {len(result.episodes)} episode(s) ready, synthesizing")

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, script in enumerate(result.episodes, 1):
                logger.info(f"[{request_id}] Synthesizing episode {i}/{len(result.episodes)}")
                audio = _build_podcast(
                    text=script,
                    language=language,
                    voice_id=voice_id or None,
                    include_intro=include_intro,
                    include_outro=include_outro,
                )
                zf.writestr(f"episode_{i:02d}.mp3", audio)
            if result.operator_message:
                zf.writestr("operator_message.txt", result.operator_message)

        zip_bytes = zip_buffer.getvalue()

    except RuntimeError as e:
        logger.error(f"[{request_id}] Generation error: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        logger.exception(f"[{request_id}] Unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during podcast generation.",
        )

    response_headers = {
        "Content-Disposition": f'attachment; filename="podcast_{request_id}.zip"',
        "X-Request-Id": request_id,
        "X-Episode-Count": str(len(result.episodes)),
    }
    if result.operator_message:
        response_headers["X-Operator-Message"] = result.operator_message

    logger.info(
        f"[{request_id}] Returning ZIP with {len(result.episodes)} episode(s) "
        f"({len(zip_bytes)} bytes)"
    )
    return Response(content=zip_bytes, media_type="application/zip", headers=response_headers)


# ──────────────────────────────────────────────────────────────────────────────
# Two-step workflow: scripts → review → synthesize
# ──────────────────────────────────────────────────────────────────────────────

class ScriptsRequest(BaseModel):
    """JSON body for the /scripts endpoint."""

    source: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description="Source material: raw text, a URL (http/https), or a file path.",
    )


class SynthesisParams(BaseModel):
    """Synthesis settings passed at MP3-generation time."""

    language: str = Field(default="en")
    voice_id: Optional[str] = Field(default=None)
    include_intro: bool = Field(default=False)
    include_outro: bool = Field(default=False)
    text_override: Optional[str] = Field(
        default=None,
        description="If provided, use this text as-is (no server-side translation applied).",
    )
    # Voice controls — all optional, fall back to sensible defaults
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    stability: float = Field(default=0.80, ge=0.0, le=1.0)
    similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0)
    style: float = Field(default=0.10, ge=0.0, le=1.0)
    use_speaker_boost: bool = Field(default=False)

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        supported = get_settings().supported_languages
        v = v.lower().strip()
        if v not in supported:
            raise ValueError(f"Language '{v}' is not supported. Choose from: {supported}")
        return v


class TranslateRequest(BaseModel):
    target_language: str
    source_text: Optional[str] = Field(
        default=None,
        description="Text to translate. If omitted, the session's stored English text is used.",
    )


class UpdateEpisodeTextRequest(BaseModel):
    text: str


class EpisodePreview(BaseModel):
    index: int
    title: str
    word_count: int
    preview: str
    is_expanded: bool


class ScriptsResponse(BaseModel):
    session_id: str
    episode_count: int
    operator_message: Optional[str]
    episodes: list[EpisodePreview]


@router.post("/scripts", summary="Phase 1: generate episode plan (conspect) from source")
async def generate_scripts_endpoint(request: ScriptsRequest) -> ScriptsResponse:
    """
    Phase 1 of the generation pipeline. Parses source once and returns a lightweight
    episode plan (titles + summaries). Fast — source is never re-sent after this call.
    Episodes are stubs; call /expand per episode to stream the full scripts.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY is not configured.",
        )

    request_id = uuid.uuid4().hex[:8]
    logger.info(f"[{request_id}] Conspect request | source={request.source[:80]!r}")

    try:
        source_text = await _resolve_source(request.source)
        logger.info(f"[{request_id}] Source resolved ({len(source_text)} chars)")

        result = generate_conspect(source_text=source_text, api_key=settings.anthropic_api_key)
        if not result.episodes:
            raise RuntimeError("No episodes could be planned from the provided source material.")

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except RuntimeError as e:
        logger.error(f"[{request_id}] Conspect error: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        logger.exception(f"[{request_id}] Unexpected error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    session = sessions.create(
        episodes=[{"index": ep.index, "title": ep.title, "summary": ep.summary} for ep in result.episodes],
        operator_message=result.operator_message,
    )
    logger.info(f"[{request_id}] Session {session.id} created: {len(session.episodes)} episode stubs")

    return ScriptsResponse(
        session_id=session.id,
        episode_count=len(session.episodes),
        operator_message=session.operator_message,
        episodes=[
            EpisodePreview(
                index=ep.index, title=ep.title,
                word_count=ep.word_count, preview=ep.preview, is_expanded=ep.is_expanded,
            )
            for ep in session.episodes
        ],
    )


@router.post(
    "/sessions/{session_id}/episodes/{episode_index}/expand",
    summary="Phase 2: stream full script for one episode (plan only — source not re-sent)",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/plain": {}}, "description": "Episode script streamed as plain text."}},
)
async def expand_episode_endpoint(session_id: str, episode_index: int) -> StreamingResponse:
    """
    Streams a full 1500-2000 word episode script using only the compact episode plan.
    The original source text is NOT re-sent to the model.
    Saves the complete text to the session once streaming finishes.
    """
    session = _get_session_or_404(session_id)
    episode = session.get_episode(episode_index)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Episode {episode_index} not found.")

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ANTHROPIC_API_KEY is not configured.")

    outlines = [
        type("EpisodeOutline", (), {"index": ep.index, "title": ep.title, "summary": ep.summary})()
        for ep in session.episodes
    ]

    # Build user content (same logic as expand_episode in script_generator)
    plan_lines = []
    for ep in session.episodes:
        marker = "*** TARGET ***" if ep.index == episode_index else ""
        plan_lines.append(f"Episode {ep.index}: {ep.title} {marker}\n{ep.summary}")
    user_content = "\n\n".join(plan_lines)

    logger.info(f"Streaming expansion: session={session_id} episode={episode_index}")

    async def stream_text():
        client = _anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        full_text: list[str] = []
        try:
            async with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=20000,
                system=EXPAND_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            ) as stream:
                async for chunk in stream.text_stream:
                    full_text.append(chunk)
                    yield chunk
            # Save completed text to session
            sessions.update_episode_text(session_id, episode_index, "".join(full_text))
            logger.info(f"Episode {episode_index} expansion complete: {sum(len(c) for c in full_text)} chars")
        except Exception as e:
            logger.error(f"Streaming error for episode {episode_index}: {e}")
            yield f"\n\n[ERROR: {e}]"

    return StreamingResponse(stream_text(), media_type="text/plain")


def _get_session_or_404(session_id: str) -> sessions.Session:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found or expired.")
    return session


@router.patch(
    "/sessions/{session_id}/episodes/{episode_index}/text",
    summary="Update episode script text",
)
async def update_episode_text_endpoint(
    session_id: str, episode_index: int, body: UpdateEpisodeTextRequest
) -> dict:
    session = _get_session_or_404(session_id)
    episode = session.get_episode(episode_index)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Episode {episode_index} not found.")
    sessions.update_episode_text(session_id, episode_index, body.text)
    return {"ok": True}


@router.post(
    "/sessions/{session_id}/episodes/{episode_index}/translate",
    summary="Stream translation of an episode to a target language",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/plain": {}}}},
)
async def translate_episode_endpoint(
    session_id: str, episode_index: int, body: TranslateRequest
) -> StreamingResponse:
    """
    Stream a translation of the episode script to the target language.
    source_text in the body is used if provided; otherwise falls back to the
    session-stored English script.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY is required for translation.",
        )

    source_text = body.source_text
    if not source_text:
        session = _get_session_or_404(session_id)
        episode = session.get_episode(episode_index)
        if not episode or not episode.is_expanded:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Episode not yet expanded and no source_text provided.",
            )
        source_text = episode.text

    lang_name = LANGUAGE_NAMES.get(body.target_language, body.target_language)
    logger.info(f"Streaming two-stage localization: session={session_id} ep={episode_index} → {lang_name}")

    async def stream_two_stage_localization():
        """
        Two-stage localization pipeline streamed to the client.

        Stage 1 (Translation): streams the direct translation in real-time.
        Stage 2 (Localization): once Stage 1 is complete, re-streams the
        idiomatic rewrite starting from a blank slate — clients will see the
        final natural-sounding text accumulate progressively.
        """
        client = _anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        try:
            # ── Stage 1: direct translation (streamed) ──────────────────────
            logger.info(f"[Stage 1] Streaming translation → {lang_name}")
            stage1_chunks: list[str] = []
            async with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=20000,
                system=TRANSLATE_SYSTEM_TEMPLATE.format(lang_name=lang_name),
                messages=[{"role": "user", "content": source_text}],
            ) as stream:
                async for chunk in stream.text_stream:
                    stage1_chunks.append(chunk)
                    yield chunk

            stage1_text = "".join(stage1_chunks)
            logger.info(f"[Stage 1] Complete: {len(stage1_text)} chars")

            # ── Stage 2: idiomatic rewrite (streamed, replaces Stage 1 output) ──
            # Signal the client to clear the current content and start Stage 2.
            # We use a zero-width sentinel that the JS client can detect to wipe
            # the textarea before the localized version streams in.
            yield "\x00"  # NUL sentinel — client clears textarea on receipt

            logger.info(f"[Stage 2] Streaming localization → native {lang_name}")
            async with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=20000,
                system=LOCALIZE_SYSTEM_TEMPLATE.format(lang_name=lang_name),
                messages=[{"role": "user", "content": stage1_text}],
            ) as stream:
                async for chunk in stream.text_stream:
                    yield chunk

            logger.info(f"[Stage 2] Localization stream complete")

        except Exception as e:
            logger.error(f"Two-stage localization stream error: {e}")
            yield f"\n\n[ERROR: {e}]"

    return StreamingResponse(stream_two_stage_localization(), media_type="text/plain")


def _ensure_output_dir(settings) -> Path:
    out = Path(settings.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    return out


async def _run_synthesis_job(
    job_id: str,
    session_id: str,
    episode_index: int,
    params: SynthesisParams,
) -> None:
    """Background task: translate if needed, synthesize, save to disk."""
    jobs.update(job_id, status=JobStatus.RUNNING)
    settings = get_settings()

    try:
        # Resolve text — text_override means already-translated text from client
        text = params.text_override
        if not text:
            session = sessions.get(session_id)
            if not session:
                raise RuntimeError("Session expired and no text_override provided.")
            episode = session.get_episode(episode_index)
            if not episode or not episode.is_expanded:
                raise RuntimeError("Episode not expanded.")
            text = episode.text

        # Server-side two-stage localization only when no text_override (client didn't pre-translate)
        if params.language != "en" and not params.text_override:
            if not settings.anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY required for translation.")
            logger.info(f"Job {job_id}: two-stage localization to {params.language}")
            text = await asyncio.to_thread(
                translate_and_localize, text, params.language, settings.anthropic_api_key
            )

        logger.info(f"Job {job_id}: synthesizing {len(text)} chars → {params.language}")
        audio = await asyncio.to_thread(
            _build_podcast,
            text, params.language, params.voice_id or None,
            params.include_intro, params.include_outro,
            params.speed, params.stability, params.similarity_boost,
            params.style, params.use_speaker_boost,
        )

        out_dir = _ensure_output_dir(settings)
        lang_suffix = f"_{params.language}" if params.language != "en" else ""
        filename = f"{session_id}_ep{episode_index:02d}{lang_suffix}.mp3"
        out_path = out_dir / filename
        out_path.write_bytes(audio)
        logger.info(f"Job {job_id}: saved {out_path} ({len(audio)} bytes)")

        jobs.update(job_id, status=JobStatus.DONE, output_path=str(out_path), filename=filename)

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        jobs.update(job_id, status=JobStatus.FAILED, error=str(e))


@router.post(
    "/sessions/{session_id}/episodes/{episode_index}/synthesize",
    summary="Queue a synthesis job for one episode",
)
async def synthesize_episode(
    session_id: str,
    episode_index: int,
    background_tasks: BackgroundTasks,
    params: SynthesisParams = SynthesisParams(),
) -> dict:
    """
    Enqueues a background synthesis job. Returns immediately with a job_id.
    Poll GET /podcast/jobs/{job_id} for status; download via GET /podcast/jobs/{job_id}/download.
    """
    # Validate episode exists (session may be gone after restart — text_override still works)
    session = sessions.get(session_id)
    if session:
        episode = session.get_episode(episode_index)
        if episode is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Episode {episode_index} not found.")
        if not episode.is_expanded and not params.text_override:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Episode not yet expanded.")
    elif not params.text_override:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or expired. Provide text_override to synthesize without a live session.",
        )

    job = jobs.create()
    background_tasks.add_task(_run_synthesis_job, job.id, session_id, episode_index, params)
    logger.info(f"Synthesis job {job.id} queued | session={session_id} ep={episode_index} lang={params.language}")
    return {"job_id": job.id, "status": job.status}


@router.get("/jobs/{job_id}", summary="Get synthesis job status")
async def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return {
        "job_id": job.id,
        "status": job.status,
        "error": job.error,
        "filename": job.filename,
    }


@router.get("/jobs/{job_id}/download", summary="Download completed synthesis job")
async def download_job(job_id: str) -> Response:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    if job.status != JobStatus.DONE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is {job.status}. Only 'done' jobs can be downloaded.",
        )
    out_path = Path(job.output_path)
    if not out_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output file missing from disk.")
    return Response(
        content=out_path.read_bytes(),
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{job.filename}"'},
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
