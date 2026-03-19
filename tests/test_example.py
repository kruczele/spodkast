"""
Example / integration tests for Spodkast.

These tests demonstrate how to use the Spodkast API and can be run
against a live instance or with mocks.

Prerequisites:
    pip install pytest pytest-asyncio httpx

Usage (with a running server at localhost:8000):
    pytest tests/ -v

Usage (with mocked ElevenLabs — no API key needed):
    pytest tests/ -v -m mock
"""

import os
import pytest
import httpx


BASE_URL = os.getenv("SPODKAST_URL", "http://localhost:8000")

SAMPLE_TEXT_EN = """
The universe began approximately 13.8 billion years ago with the Big Bang.
In the vast expanse of cosmic time, our solar system formed about 4.6 billion years ago
from a cloud of gas and dust. Earth, our pale blue dot, emerged from this primordial soup
and over billions of years gave rise to the magnificent tapestry of life we see today.
Tonight, as you drift off to sleep, ponder the incredible journey that brought you here.
"""

SAMPLE_TEXT_PL = """
Wszechświat rozpoczął swoje istnienie około 13,8 miliarda lat temu podczas Wielkiego Wybuchu.
W ogromnej przestrzeni kosmicznego czasu nasz układ słoneczny uformował się około 4,6 miliarda
lat temu z obłoku gazu i pyłu. Ziemia, nasza blada niebieska kropka, wyłoniła się z tej
pierwotnej zupki i przez miliardy lat dała początek wspaniałej tkaninie życia.
"""

SAMPLE_TEXT_ES = """
El universo comenzó hace aproximadamente 13.800 millones de años con el Big Bang.
En la vasta extensión del tiempo cósmico, nuestro sistema solar se formó hace unos
4.600 millones de años a partir de una nube de gas y polvo. La Tierra, nuestro pálido
punto azul, emergió de esta sopa primordial y a lo largo de miles de millones de años
dio origen al magnífico tapiz de vida que vemos hoy.
"""


@pytest.mark.asyncio
async def test_health():
    """Service health check should return 200 OK."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_list_languages():
    """Languages endpoint should return at least en, pl, es."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        response = await client.get("/podcast/languages")
    assert response.status_code == 200
    data = response.json()
    assert "en" in data["supported_languages"]
    assert "pl" in data["supported_languages"]
    assert "es" in data["supported_languages"]


@pytest.mark.asyncio
async def test_synthesize_english():
    """Synthesize English article — should return MP3 audio."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120) as client:
        response = await client.post(
            "/podcast/synthesize",
            json={
                "text": SAMPLE_TEXT_EN,
                "language": "en",
                "include_intro": False,
                "include_outro": False,
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert len(response.content) > 1000, "Audio response seems too short"


@pytest.mark.asyncio
async def test_synthesize_polish():
    """Synthesize Polish article — should return MP3 audio."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120) as client:
        response = await client.post(
            "/podcast/synthesize",
            json={
                "text": SAMPLE_TEXT_PL,
                "language": "pl",
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"


@pytest.mark.asyncio
async def test_synthesize_spanish():
    """Synthesize Spanish article — should return MP3 audio."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120) as client:
        response = await client.post(
            "/podcast/synthesize",
            json={
                "text": SAMPLE_TEXT_ES,
                "language": "es",
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"


@pytest.mark.asyncio
async def test_unsupported_language():
    """Unsupported language should return 422 validation error."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        response = await client.post(
            "/podcast/synthesize",
            json={
                "text": SAMPLE_TEXT_EN,
                "language": "xx",
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_text_too_short():
    """Text shorter than 10 chars should be rejected with 422."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        response = await client.post(
            "/podcast/synthesize",
            json={"text": "Hi", "language": "en"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_synthesize_with_intro_outro():
    """
    Synthesize with intro/outro enabled.
    Audio samples must exist at audio/samples/intro.mp3 and audio/samples/outro.mp3.
    Skip if samples are not present.
    """
    import os
    if not (
        os.path.exists("audio/samples/intro.mp3")
        and os.path.exists("audio/samples/outro.mp3")
    ):
        pytest.skip("Intro/outro samples not present — skipping mix test")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120) as client:
        response = await client.post(
            "/podcast/synthesize",
            json={
                "text": SAMPLE_TEXT_EN,
                "language": "en",
                "include_intro": True,
                "include_outro": True,
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"


# ──────────────────────────────────────────────────────────────────────────────
# Direct usage example (run as script)
# ──────────────────────────────────────────────────────────────────────────────

def example_direct_usage():
    """
    Demonstrates direct Python usage of the synthesis pipeline.
    Run with: python tests/test_example.py
    Requires: ELEVENLABS_API_KEY set in .env
    """
    import sys
    sys.path.insert(0, ".")

    from dotenv import load_dotenv
    load_dotenv()

    from app.tts import synthesize_text
    from app.audio_mixer import mix_podcast

    print("🎙️  Spodkast — Direct Usage Example")
    print("=" * 50)

    text = SAMPLE_TEXT_EN.strip()
    print(f"Text length: {len(text)} chars")
    print("Synthesizing English narration...")

    narration = synthesize_text(text=text, language="en")
    print(f"Narration: {len(narration)} bytes")

    print("Mixing audio (no intro/outro)...")
    final_audio = mix_podcast(narration_bytes=narration)
    print(f"Final audio: {len(final_audio)} bytes")

    output_path = "output/example_podcast.mp3"
    with open(output_path, "wb") as f:
        f.write(final_audio)

    print(f"✅ Podcast saved to: {output_path}")


if __name__ == "__main__":
    example_direct_usage()
