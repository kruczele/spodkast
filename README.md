# 🎙️ Spodkast

**Article-to-Podcast service** — converts written articles into calm, soothing podcast-style audio using [ElevenLabs](https://elevenlabs.io) TTS.

Designed for the **"goodnight read"** experience: warm, steady narration that's perfect for winding down.

---

## Features

- 🌍 **Multi-language support** — English, Polish, Spanish (easily extensible to 20+ languages)
- 🎵 **Intro/outro injection** — seamlessly mix ambient music before and after narration
- 🎚️ **Audio mixing** — FFmpeg-powered via Pydub (crossfade, normalization)
- ⚡ **FastAPI service** — REST endpoints, auto-generated OpenAPI docs
- 📝 **Production-grade** — structured logging (Loguru), input validation (Pydantic), error handling

---

## Quick Start

### 1. Clone and set up

```bash
git clone https://github.com/kruczele/spodkast.git
cd spodkast

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Install FFmpeg (required for audio mixing)

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt-get install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html and add to PATH
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set your ElevenLabs API key:

```env
ELEVENLABS_API_KEY=your_key_here
```

Get your API key at: https://elevenlabs.io/app/settings/api-keys

### 4. Start the service

```bash
uvicorn app.main:app --reload
```

The API will be available at **http://localhost:8000**
Interactive docs: **http://localhost:8000/docs**

---

## API Usage

### Synthesize an article (JSON)

```bash
curl -X POST http://localhost:8000/podcast/synthesize \
  -H "Content-Type: application/json" \
  -d '{
    "text": "The universe began 13.8 billion years ago...",
    "language": "en",
    "include_intro": false,
    "include_outro": false
  }' \
  --output podcast.mp3
```

### Synthesize with a custom intro/outro upload

```bash
curl -X POST http://localhost:8000/podcast/synthesize/form \
  -F "text=Your article text here..." \
  -F "language=en" \
  -F "intro_file=@/path/to/intro.mp3" \
  -F "outro_file=@/path/to/outro.mp3" \
  --output podcast.mp3
```

### List supported languages

```bash
curl http://localhost:8000/podcast/languages
```

Response:
```json
{
  "supported_languages": ["en", "pl", "es"],
  "voice_map": {
    "en": "21m00Tcm4TlvDq8ikWAM",
    "pl": "21m00Tcm4TlvDq8ikWAM",
    "es": "21m00Tcm4TlvDq8ikWAM"
  },
  "model": "eleven_multilingual_v2"
}
```

### Python (direct usage)

```python
from app.tts import synthesize_text
from app.audio_mixer import mix_podcast

# Synthesize narration
narration = synthesize_text(
    text="Your article content here...",
    language="en"
)

# Mix with intro/outro
final_audio = mix_podcast(
    narration_bytes=narration,
    intro_path="audio/samples/intro.mp3",   # optional
    outro_path="audio/samples/outro.mp3",   # optional
)

# Save
with open("output/podcast.mp3", "wb") as f:
    f.write(final_audio)
```

---

## Multi-Language Support

Spodkast uses ElevenLabs' **`eleven_multilingual_v2`** model, which natively supports 29 languages:

| Code | Language   | Notes |
|------|-----------|-------|
| `en` | English    | Primary — Rachel voice (calm, warm) |
| `pl` | Polish     | Native multilingual support |
| `es` | Spanish    | Native multilingual support |

### Adding More Languages

1. Find a suitable voice in the [ElevenLabs Voice Library](https://elevenlabs.io/app/voice-library)
   - Filter by language
   - Look for "calm", "warm", or "storyteller" style voices
   - Copy the Voice ID

2. Add to `.env`:
   ```env
   VOICE_ID_DE=<voice_id_for_german>
   ```

3. Extend `app/config.py`:
   ```python
   voice_id_de: str = Field(default="...", env="VOICE_ID_DE")

   @property
   def voice_map(self) -> Dict[str, str]:
       return {
           "en": self.voice_id_en,
           "pl": self.voice_id_pl,
           "es": self.voice_id_es,
           "de": self.voice_id_de,   # ← add here
       }
   ```

### Supported Languages (eleven_multilingual_v2)

English, Polish, Spanish, German, French, Italian, Portuguese, Hindi, Arabic, Czech, Chinese, Japanese, Hungarian, Korean, Dutch, Turkish, Swedish, Romanian, Norwegian, Danish, Finnish, Slovak, Croatian, Malay, Tamil, Ukrainian, Filipino, Bulgarian, Greek.

---

## Voice Tuning

The narration voice is tuned for calm "goodnight read" style in `app/tts.py`:

```python
CALM_VOICE_SETTINGS = VoiceSettings(
    stability=0.80,        # High stability → steady, consistent delivery
    similarity_boost=0.75, # Moderate → natural sound
    style=0.10,            # Low style → minimal expressiveness, calm tone
    use_speaker_boost=False # Keeps voice gentle, not projected
)
```

To adjust the feel:
- **More expressive**: increase `style` (0.3–0.5)
- **More consistent**: increase `stability` (0.85–0.95)
- **More dramatic**: increase `style` and decrease `stability`

---

## Intro/Outro Audio

Place audio files in `audio/samples/`:

```
audio/samples/
├── intro.mp3      ← played before narration
├── outro.mp3      ← played after narration
└── README.md      ← tips and free music resources
```

The mixer applies a **1.5-second crossfade** between segments for smooth transitions.

### Free "Goodnight Read" Music Sources

- [Pixabay Music](https://pixabay.com/music/) — search "ambient", "sleep", "lo-fi"
- [Free Music Archive](https://freemusicarchive.org/) — filter by Creative Commons
- [ccMixter](http://ccmixter.org/) — creative commons licensed

---

## Project Structure

```
spodkast/
├── app/
│   ├── main.py          # FastAPI app, lifespan, middleware
│   ├── config.py        # Settings via pydantic-settings
│   ├── tts.py           # ElevenLabs TTS integration
│   ├── audio_mixer.py   # pydub audio mixing (intro/outro/crossfade)
│   └── routers/
│       └── podcast.py   # /podcast/* endpoints
├── audio/
│   └── samples/         # Drop intro.mp3 / outro.mp3 here
├── output/              # Generated audio files (git-ignored)
├── logs/                # Rotating log files (git-ignored)
├── tests/
│   └── test_example.py  # Integration tests + direct usage example
├── .env.example         # Environment template
├── requirements.txt     # Python dependencies
└── README.md
```

---

## Running Tests

```bash
# Start the service first
uvicorn app.main:app &

# Run tests
pip install pytest pytest-asyncio
pytest tests/ -v
```

Or run the direct usage example (bypasses HTTP):

```bash
python tests/test_example.py
```

---

## ElevenLabs API Limits

| Plan   | Characters/month | Concurrent requests |
|--------|-----------------|---------------------|
| Free   | 10,000          | 1                   |
| Starter| 30,000          | 3                   |
| Creator| 100,000         | 10                  |

A typical 1,000-word article ≈ 6,000 characters.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ELEVENLABS_API_KEY` | ✅ | — | Your ElevenLabs API key |
| `ELEVENLABS_MODEL_ID` | | `eleven_multilingual_v2` | ElevenLabs model |
| `VOICE_ID_EN` | | `21m00Tcm4TlvDq8ikWAM` | Voice for English |
| `VOICE_ID_PL` | | `21m00Tcm4TlvDq8ikWAM` | Voice for Polish |
| `VOICE_ID_ES` | | `21m00Tcm4TlvDq8ikWAM` | Voice for Spanish |
| `AUDIO_OUTPUT_FORMAT` | | `mp3_44100_128` | ElevenLabs output format |
| `OUTPUT_DIR` | | `./output` | Directory for generated files |
| `HOST` | | `0.0.0.0` | Server host |
| `PORT` | | `8000` | Server port |
| `LOG_LEVEL` | | `INFO` | Logging level |

---

## License

MIT
