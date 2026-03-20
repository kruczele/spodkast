"""
Audio mixing utilities for Spodkast.
Handles injection of intro/outro segments and audio assembly using pydub.

System requirement: ffmpeg must be installed and on PATH.
Install: https://ffmpeg.org/download.html
  macOS:  brew install ffmpeg
  Ubuntu: apt-get install ffmpeg
  Windows: winget install ffmpeg
"""

import io
import os
import shutil
from pathlib import Path
from typing import Optional
from loguru import logger
from pydub import AudioSegment
from pydub.effects import normalize


def check_ffmpeg() -> None:
    """Raise RuntimeError if ffmpeg binary is not available on PATH."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg is not installed or not on PATH. "
            "Spodkast requires ffmpeg for audio processing. "
            "Install it and ensure it is accessible from the command line.\n"
            "  macOS:  brew install ffmpeg\n"
            "  Ubuntu: apt-get install ffmpeg\n"
            "  Windows: winget install ffmpeg"
        )


# Crossfade duration (ms) for smooth intro/outro transitions
CROSSFADE_MS = 1500


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
        [intro] → [narration] → [outro]

    Crossfade is applied between segments for a smooth listening experience.
    When no intro or outro is provided, the narration bytes are returned
    directly without lossy re-encoding through pydub (fast path).

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
    has_intro = bool(intro_path and os.path.exists(intro_path))
    has_outro = bool(outro_path and os.path.exists(outro_path))

    # Fast path: no mixing needed — avoid lossy re-encode through pydub
    if not has_intro and not has_outro:
        if intro_path and not has_intro:
            logger.warning(f"Intro file not found: {intro_path}, skipping")
        if outro_path and not has_outro:
            logger.warning(f"Outro file not found: {outro_path}, skipping")
        logger.info("No intro/outro to mix — returning narration directly")
        return narration_bytes

    # Full mixing path — requires ffmpeg
    check_ffmpeg()

    # Load narration
    narration = _load_audio(narration_bytes)
    if normalize_audio:
        narration = normalize(narration)
    logger.info(f"Narration duration: {len(narration) / 1000:.1f}s")

    segments = []

    # Add intro (existence already confirmed via has_intro above)
    if has_intro:
        try:
            intro = _load_audio(intro_path)
            if normalize_audio:
                intro = normalize(intro)
            segments.append(intro)
            logger.info(f"Intro loaded: {len(intro) / 1000:.1f}s")
        except Exception as e:
            logger.warning(f"Failed to load intro, skipping: {e}")

    segments.append(narration)

    # Add outro (existence already confirmed via has_outro above)
    if has_outro:
        try:
            outro = _load_audio(outro_path)
            if normalize_audio:
                outro = normalize(outro)
            segments.append(outro)
            logger.info(f"Outro loaded: {len(outro) / 1000:.1f}s")
        except Exception as e:
            logger.warning(f"Failed to load outro, skipping: {e}")

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

    Crossfade is applied directly between audio segments (no silence prepend,
    which would cause a double-fade artifact where the outgoing segment fades
    into silence before the incoming segment fades up).
    """
    result = segments[0]

    for seg in segments[1:]:
        # Crossfade directly into the audio content of the next segment
        xfade = min(CROSSFADE_MS, len(result) // 2, len(seg) // 2)
        result = result.append(seg, crossfade=xfade)

    return result
