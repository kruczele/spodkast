"""
Spodkast - Article-to-Podcast Service
Entry point for the FastAPI application.
"""

import sys
import os
import shutil
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import get_settings
from app.routers import podcast


# ──────────────────────────────────────────────────────────────────────────────
# Logging setup
# ──────────────────────────────────────────────────────────────────────────────

def configure_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
    )
    logger.add(
        "logs/spodkast.log",
        level=level,
        rotation="10 MB",
        retention="14 days",
        compression="gz",
        enqueue=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Lifespan (startup / shutdown)
# ──────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Ensure output and logs directories exist BEFORE configuring logging
    # (the file sink needs the logs/ dir to already exist)
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(parents=True, exist_ok=True)

    configure_logging(settings.log_level)

    # Fail fast: ffmpeg is required for audio mixing
    if shutil.which("ffmpeg") is None:
        logger.error(
            "ffmpeg is not installed or not on PATH. "
            "Spodkast requires ffmpeg for audio processing when using intro/outro mixing. "
            "Install it: macOS: brew install ffmpeg | Ubuntu: apt-get install ffmpeg"
        )
        # Don't crash startup — service can still handle plain synthesize requests
        # (fast path avoids pydub). Log the warning so operators are aware.

    logger.info("🎙️  Spodkast service starting up")
    logger.info(f"   Supported languages: {settings.supported_languages}")
    logger.info(f"   ElevenLabs model: {settings.elevenlabs_model_id}")
    logger.info(f"   Output directory: {settings.output_dir}")

    yield

    logger.info("Spodkast service shutting down")


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Spodkast",
    summary="Article-to-Podcast service powered by ElevenLabs TTS",
    description=(
        "Convert written articles into calm, soothing podcast-style audio. "
        "Supports English, Polish, and Spanish. "
        "Optionally wraps narration with intro/outro audio segments."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — wildcard origin without credentials (CORS spec forbids combining
# allow_origins=["*"] with allow_credentials=True; browsers reject such responses).
# For production: replace allow_origins with specific frontend origins and
# set allow_credentials=True if cookies/auth headers are needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(podcast.router)


# ──────────────────────────────────────────────────────────────────────────────
# Health / root endpoints
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "service": "spodkast",
        "version": "0.1.0",
        "status": "ok",
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}
