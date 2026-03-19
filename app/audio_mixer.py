"""
Audio mixing utilities for Spodkast.
Handles injection of intro/outro segments and audio assembly using pydub.
"""

import io
import os
from pathlib import Path
from typing import Optional
from loguru import logger
from pydub import AudioSegment
from pydub.effects import normalize


# Crossfade duration (ms) for smooth intro/outro transitions
CROSSFADE_MS = 1500

# Short silence padding between segments (ms)
SILENCE_BETWEEN_MS = 500


def _load_audio(source: bytes | str | Path) -> AudioSegment:
    """
    Load audio from bytes or a file path.

    Args:
        source: Raw audio bytes or path to an audio file.

    Returns:
        AudioSegment instance.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")
        logger.debug(f"Loading audio file: {path}")
        return AudioSegment.from_file(path)

    # bytes
    logger.debug(f"Loading audio from bytes ({len(source)} bytes)")
    return AudioSegment.from_file(io.BytesIO(source))


def mix_podcast(
    narration_bytes: bytes,
    intro_path: Optional[str | Path] = None,
    outro_path: Optional[str | Path] = None,
    normalize_audio: bool = True,
    output_format: str = "mp3",
    bitrate: str = "128k",
) -> bytes:
    """
    Mix narration audio with optional intro and outro segments.

    Assembly order:
        [intro] → [short silence] → [narration] → [short silence] → [outro]

    Crossfade is applied between segments for a smooth listening experience.

    Args:
        narration_bytes: Raw bytes of the synthesized narration audio.
        intro_path: Optional path to intro audio file (MP3/WAV/OGG).
        outro_path: Optional path to outro audio file (MP3/WAV/OGG).
        normalize_audio: Normalize each segment's volume before mixing.
        output_format: Output audio format ('mp3', 'wav', 'ogg').
        bitrate: Output bitrate for lossy formats.

    Returns:
        Mixed audio as bytes.
    """
    # Load narration
    narration = _load_audio(narration_bytes)
    if normalize_audio:
        narration = normalize(narration)
    logger.info(f"Narration duration: {len(narration) / 1000:.1f}s")

    segments = []

    # Add intro
    if intro_path and os.path.exists(intro_path):
        try:
            intro = _load_audio(intro_path)
            if normalize_audio:
                intro = normalize(intro)
            segments.append(intro)
            logger.info(f"Intro loaded: {len(intro) / 1000:.1f}s")
        except Exception as e:
            logger.warning(f"Failed to load intro, skipping: {e}")
    elif intro_path:
        logger.warning(f"Intro file not found: {intro_path}, skipping")

    segments.append(narration)

    # Add outro
    if outro_path and os.path.exists(outro_path):
        try:
            outro = _load_audio(outro_path)
            if normalize_audio:
                outro = normalize(outro)
            segments.append(outro)
            logger.info(f"Outro loaded: {len(outro) / 1000:.1f}s")
        except Exception as e:
            logger.warning(f"Failed to load outro, skipping: {e}")
    elif outro_path:
        logger.warning(f"Outro file not found: {outro_path}, skipping")

    # Assemble final podcast audio
    if len(segments) == 1:
        # No intro/outro — return narration as-is
        final = segments[0]
    else:
        final = _join_with_crossfade(segments)

    logger.info(f"Final podcast duration: {len(final) / 1000:.1f}s")

    # Export to bytes
    output_buffer = io.BytesIO()
    export_kwargs = {"format": output_format}
    if output_format in ("mp3", "ogg"):
        export_kwargs["bitrate"] = bitrate

    final.export(output_buffer, **export_kwargs)
    output_bytes = output_buffer.getvalue()
    logger.info(f"Exported audio: {len(output_bytes)} bytes ({output_format})")
    return output_bytes


def _join_with_crossfade(segments: list[AudioSegment]) -> AudioSegment:
    """
    Join multiple audio segments with crossfade transitions.

    A short silence is padded between segments before crossfading to prevent
    abrupt cuts.
    """
    silence = AudioSegment.silent(duration=SILENCE_BETWEEN_MS)
    result = segments[0]

    for seg in segments[1:]:
        # Pad with silence for breathing room, then crossfade
        padded = silence + seg
        xfade = min(CROSSFADE_MS, len(result) // 2, len(padded) // 2)
        result = result.append(padded, crossfade=xfade)

    return result
