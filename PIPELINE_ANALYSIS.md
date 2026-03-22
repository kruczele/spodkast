# Spodkast: Self-Contained Podcast Pipeline — Gap Analysis

**Goal:** Generate fall-asleep podcasts with fun facts delivered in a calm, boring voice to help listeners learn while falling asleep — fully autonomously, without any manual input.

**Analysis Date:** 2026-03-22
**Repository:** [kruczele/spodkast](https://github.com/kruczele/spodkast)
**Codebase Snapshot:** commit `8dc41fc` (main as of analysis date)

---

## TL;DR — Current State

Spodkast is a **production-quality article-to-podcast API** built on FastAPI + ElevenLabs TTS + Claude. It generates high-quality, sleep-tuned audio from source material supplied by the user. The core content pipeline, TTS voice tuning, audio mixing, multi-language support, and session persistence are all **solid and working**.

**The fundamental gap:** every step of the pipeline currently requires manual human input. There is no autonomous content sourcing, no scheduling, no RSS feed, and no distribution layer. The system is a tool, not a pipeline.

| Dimension | Status | Gap Severity |
|-----------|--------|-------------|
| Content generation pipeline | ✅ Exists (manual input required) | CRITICAL |
| TTS / voice generation | ✅ Well-tuned for sleep content | LOW |
| Audio processing | ✅ Functional; some advanced features missing | MEDIUM |
| Podcast structure / metadata | ⚠️ Episodes in SQLite; no RSS/ID3 | CRITICAL |
| Distribution infrastructure | ❌ None | CRITICAL |
| Automation & scheduling | ❌ None | CRITICAL |
| Data sources / fun facts | ❌ None (user-supplied only) | CRITICAL |
| Voice characteristics | ✅ Tuned for boring delivery | LOW |
| Quality control | ✅ Solid test suite; no audio QA | MEDIUM |
| Documentation & maintenance | ✅ Excellent dev docs; missing ops docs | MEDIUM |

---

## 1. Content Generation Pipeline

### What Exists

The pipeline is a two-phase LLM system using Claude (`claude-sonnet-4-6`):

**Phase 1 — Conspect** (`app/script_generator.py::generate_conspect`):
- Takes raw source material (text, URL, or file path)
- Produces a structured episode plan: up to 8 episodes, each with a `title` and dense `summary`
- Returns an `operator_message` if the source was insufficient for 8 episodes
- Prompt is explicitly sleep-tuned: "calm and descriptive, not clickbait", "no narrative arcs", "low emotional intensity"

**Phase 2 — Expansion** (`app/script_generator.py::expand_episode`):
- Takes only the compact plan (source is NOT re-sent — efficient and cheap)
- Streams 1500–2000 word scripts per episode
- Script structure enforces:
  - Soft opening, independent segments, slightly looser final phase
  - No ellipsis, no rhetorical questions, no humor, no emphasis spikes
  - Ends mid-thought (no closing phrase — deliberately abrupt for sleep)

**Localization** (two-stage: translate → idiomatic rewrite):
- Stage 1: Literal translation to target language
- Stage 2: Native-sounding rewrite by a language-specialist model
- Supported: Polish, Spanish, German, French, Italian, Portuguese, Japanese, Chinese

**Source resolution** (`routers/podcast.py::_resolve_source`):
- Raw text: returned as-is
- HTTP/HTTPS URLs: fetched, HTML tags stripped
- File paths (`/abs`, `./rel`, `~/home`): read from disk

### What Is Missing

**Autonomous content discovery** — the entire "where do the fun facts come from" layer is absent. Every invocation requires a human to paste text, provide a URL, or upload a file. There is no:

- Wikipedia API integration (Random article, Featured article, or "Fun fact" summaries)
- General trivia database (Open Trivia DB, Numbers API, Useless Facts API)
- "This Day in History" API (historical facts → episode topic)
- News aggregator (NewsAPI, Guardian API, HackerNews feed) for educational summaries
- RSS feed reader (auto-generate episodes from followed feeds)
- Pre-curated knowledge base of fun-fact topics
- LLM-based source quality gate (screen for low-quality or inappropriate material)

**Recommendations (Priority 1):**

```python
# Proposed: app/content_sources.py

async def fetch_wikipedia_random(min_words: int = 500) -> str:
    """Pull a random Wikipedia article suitable for a podcast episode."""
    resp = await httpx.get(
        "https://en.wikipedia.org/api/rest_v1/page/random/summary"
    )
    return resp.json()["extract"]

async def fetch_this_day_facts(date: datetime | None = None) -> str:
    """Pull 'This Day in History' facts from Wikipedia."""
    d = date or datetime.utcnow()
    url = f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{d.month}/{d.day}"
    resp = await httpx.get(url)
    events = resp.json()["events"][:10]
    return "\n\n".join(e["text"] for e in events)

async def fetch_trivia_facts(count: int = 30) -> str:
    """Pull random trivia from Open Trivia DB."""
    resp = await httpx.get(
        f"https://opentdb.com/api.php?amount={count}&type=multiple"
    )
    questions = resp.json()["results"]
    return "\n".join(q["question"] for q in questions)
```

---

## 2. Text-to-Speech (TTS) System

### What Exists

The TTS layer (`app/tts.py`) is **already well-tuned for "boring" delivery**. The ElevenLabs voice parameters are carefully configured:

```python
CALM_VOICE_SETTINGS = VoiceSettings(
    stability=0.80,          # High: steady, consistent — prevents excitement variance
    similarity_boost=0.75,   # Moderate: sounds natural without amplifying energy
    style=0.10,              # VERY LOW: minimal expressiveness — the key "boring" dial
    use_speaker_boost=False  # Off: keeps voice gentle, not projected
)
```

**Default Voice: Nicole** (ID: `piTKgcLEGmPE4e6mEKli`)
- Described in `.env.example` as "whispery ASMR voice, ideal for sleep content"
- Uses `eleven_multilingual_v2` model — handles all 29+ languages from a single voice

**Runtime control:** All voice parameters are exposed via the API:
- `speed` (0.5–2.0): default 1.0; reduce for slower pacing
- `stability` (0.0–1.0): default 0.80
- `similarity_boost` (0.0–1.0): default 0.75
- `style` (0.0–1.0): default 0.10 (key boring dial)
- `use_speaker_boost` (bool): default False

**Voice library** (`app/voices.py`) documents curated sleep-friendly voices:
- Rachel: calm, warm, gentle
- Matilda: soft, friendly, bedtime stories
- Bill: deep, steady, soothing evening reads
- Charlotte (multilingual): very calm, excellent for Polish narration

### What Is Missing

**Slower-pace defaults for sleep content:** The current `speed=1.0` is standard speech rate. For a fall-asleep podcast specifically, a default of `speed=0.85` or even `0.80` would be more effective — listeners are trying to drift off, not stay engaged.

**No pre-configured "boring" profile:** The API has all the right knobs but no named preset. A `SleepMode` preset with `speed=0.85, stability=0.90, style=0.05` would make the intent explicit and guessable for new users.

**No speech pacing prompts in the script:** The LLM scripts don't use SSML or ElevenLabs voice marks to insert pauses between sentences. Longer pauses (0.5–1.0s) between paragraphs would significantly enhance the sleep-inducing quality.

**Recommendations (Priority 2):**

```python
# In app/tts.py — add a named profile
SLEEP_VOICE_SETTINGS = VoiceSettings(
    stability=0.90,       # Very high stability for monotone consistency
    similarity_boost=0.70,
    style=0.05,           # Near-zero style → nearly flat delivery
    use_speaker_boost=False,
    speed=0.85,           # Slightly slower — 15% reduction aids sleep
)
```

```python
# In app/script_generator.py — append to EXPAND_SYSTEM
"""
## PACING NOTES
Insert a blank line between each paragraph.
This creates a natural pause in the narration.
Aim for shorter sentences in the final third.
"""
```

---

## 3. Audio Processing

### What Exists

The audio mixer (`app/audio_mixer.py`) handles the assembly pipeline cleanly:

- **Segment assembly:** `[intro] → [narration] → [outro]` with 1.5-second crossfades
- **Normalization:** Per-segment volume leveling via `pydub.effects.normalize`
- **Fast path:** If no intro/outro, returns narration bytes directly without re-encoding (preserves quality)
- **Format output:** MP3 (128k default), WAV, OGG
- **FFmpeg dependency:** Checked at startup; warning logged if missing (service still handles plain TTS without intro/outro)

### What Is Missing

**No actual intro/outro audio files are bundled.** `audio/samples/` contains only a `README.md`. Users must supply their own files. For a self-contained pipeline, at minimum a short ambient track should be bundled (or auto-downloaded from a permissive source).

**No ID3 metadata tagging.** The MP3 files are raw audio with no embedded metadata. Podcast platforms (and local media players) use ID3v2 tags to display episode title, show name, episode number, artwork, and description. The `mutagen` library (pure Python, no native deps) can add these in ~10 lines of code.

**No LUFS-targeted loudness normalization.** The current `pydub.effects.normalize` is peak normalization (raises max sample to 0 dBFS), which doesn't match the podcast industry standard of -14 to -16 LUFS. `pyloudnorm` (also pure Python) can compute and apply LUFS targets.

**No volume ducking.** For a polished sleep podcast, ambient intro/outro music should fade under the narration (not abruptly cross-fade). This requires mixing at different volume levels rather than full-volume crossfade.

**Recommendations (Priority 3):**

```python
# Install: pip install mutagen pyloudnorm

# In app/audio_mixer.py — add ID3 tagging
def tag_mp3(
    audio_bytes: bytes,
    title: str,
    episode_number: int,
    show_name: str = "Spodkast",
    show_description: str = "Fun facts for falling asleep",
    cover_art_path: str | None = None,
) -> bytes:
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, COMM, APIC
    # ... attach tags and return modified bytes
```

---

## 4. Podcast Structure: Episode Organization, Metadata, and RSS

### What Exists

Episodes are stored in SQLite with:
- `session_id` (parent identifier)
- `idx` (1-based episode index within session)
- `title` (from conspect)
- `summary` (planning notes — usable as show notes)
- `text` (full script, when expanded)
- `episode_translations` (translated scripts, cached per language)

Jobs track the synthesis output:
- `output_path` (MP3 path on disk)
- `filename` (nameable for download)
- `status` (pending → running → done → failed)
- 7-day TTL on both sessions and jobs

### What Is Missing

There is **no concept of a podcast "show"** — a persistent top-level entity with:
- Show name, description, artwork, category, author
- Show-level RSS/Atom feed

There is **no RSS feed generation.** Podcast platforms (Spotify, Apple, Google) require a publicly accessible RSS 2.0 feed with `<itunes:*>` namespace extensions. Without this, there is no way to submit the show to any platform.

There is **no persistent episode catalog.** Sessions expire in 7 days. A long-running podcast needs episodes stored indefinitely, with sequential numbering across sessions.

**Recommendations (Priority 1):**

```python
# New table: show (singleton)
CREATE TABLE show (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    name        TEXT NOT NULL DEFAULT 'Spodkast',
    description TEXT,
    author      TEXT,
    cover_url   TEXT,       -- URL to 3000×3000 JPEG artwork
    category    TEXT DEFAULT 'Education',
    language    TEXT DEFAULT 'en',
    updated_at  TEXT NOT NULL
);

# New table: published_episodes (permanent, no TTL)
CREATE TABLE published_episodes (
    episode_number INTEGER PRIMARY KEY,
    title          TEXT NOT NULL,
    description    TEXT,          -- show notes
    audio_url      TEXT NOT NULL, -- public URL to MP3
    duration_s     INTEGER,       -- seconds
    file_size_b    INTEGER,       -- bytes
    published_at   TEXT NOT NULL, -- ISO-8601
    guid           TEXT UNIQUE NOT NULL
);
```

```python
# New endpoint: GET /feeds/rss
def generate_rss_feed(show: Show, episodes: list[PublishedEpisode]) -> str:
    """Return RSS 2.0 XML with iTunes extensions."""
    # Use feedgen or hand-craft XML
    # Required tags per episode: guid, title, description,
    #   enclosure (url, length, type=audio/mpeg), pubDate,
    #   itunes:duration, itunes:episode, itunes:summary
```

---

## 5. Deployment Infrastructure

### What Exists

The service starts with `uvicorn app.main:app --reload`. That's it. There is no:

- Dockerfile
- docker-compose.yml
- Kubernetes manifests
- systemd service file
- Cloud platform configuration (Heroku `Procfile`, Railway `railway.toml`, Render `render.yaml`)
- Reverse proxy configuration (nginx, Caddy)
- HTTPS termination
- Authentication/API key protection

### What Is Missing

**For a self-contained production pipeline, the minimum deployment stack is:**

1. **Dockerfile** — reproducible, portable environment with ffmpeg pre-installed
2. **docker-compose.yml** — single-command local startup with volume mounts for SQLite + output
3. **GitHub Actions CI** — run tests on every push; optionally trigger episode generation on schedule
4. **A public host** — the RSS feed must be publicly accessible; the MP3 files need public URLs

**Recommendations (Priority 2):**

```dockerfile
# Dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p output logs audio/samples
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
version: "3.9"
services:
  spodkast:
    build: .
    ports: ["8000:8000"]
    volumes:
      - ./output:/app/output
      - ./audio/samples:/app/audio/samples
      - spodkast_db:/app/data
    env_file: .env
    environment:
      DB_PATH: /app/data/spodkast.db
      OUTPUT_DIR: /app/output
volumes:
  spodkast_db:
```

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v --ignore=tests/test_example.py
```

---

## 6. Automation & Scheduling

### What Exists

Background synthesis jobs run via FastAPI's `BackgroundTasks`. This is a single-process async mechanism — perfectly sufficient for on-demand synthesis, but not for scheduled autonomous operation.

There is no:
- Periodic task scheduler (APScheduler, Celery Beat, cron)
- GitHub Actions scheduled workflow (`on: schedule:`)
- Queue-based task dispatch
- Trigger to auto-generate a new episode on a given cadence

### What Is Missing

For a fully autonomous pipeline, the system needs a **scheduler** that, on a configurable cadence (e.g., nightly), will:

1. Pull content from a configured source (Wikipedia, trivia API, news feed)
2. Call `generate_conspect()` on the fetched content
3. Call `expand_episode()` for each episode in the plan
4. Call `synthesize_text()` + `mix_podcast()` for each script
5. Tag the resulting MP3 with ID3 metadata
6. Save the MP3 to a public CDN or static file server
7. Append the episode to the RSS feed

**Recommendations (Priority 1):**

```python
# New: app/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job("cron", hour=2, minute=0)  # 2 AM daily
async def generate_daily_episode():
    """Autonomous daily episode generation."""
    from app.content_sources import fetch_wikipedia_random
    from app.script_generator import generate_conspect, expand_episode
    from app.tts import synthesize_text
    from app.audio_mixer import mix_podcast

    source = await fetch_wikipedia_random(min_words=1000)
    plan = generate_conspect(source, api_key=settings.anthropic_api_key)
    for outline in plan.episodes[:1]:  # One episode per day
        script = expand_episode(plan.episodes, outline.index, settings.anthropic_api_key)
        audio = synthesize_text(script, language="en")
        final = mix_podcast(audio, intro_path="audio/samples/intro.mp3")
        # → save to disk, update DB, rebuild RSS feed
```

```yaml
# Alternative: .github/workflows/generate.yml
name: Daily Episode
on:
  schedule:
    - cron: "0 2 * * *"  # 2 AM UTC daily
  workflow_dispatch:      # also triggerable manually
jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt && apt-get install -y ffmpeg
      - run: python scripts/generate_episode.py
        env:
          ELEVENLABS_API_KEY: ${{ secrets.ELEVENLABS_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## 7. Data Sources — Fun Facts

### What Exists

None. All content is user-supplied.

### What Is Missing

For an autonomous fun-facts sleep podcast, a curated set of content sources is required. The following public APIs are free-tier suitable and well-maintained:

| Source | API | Data Type | Rate Limit |
|--------|-----|-----------|-----------|
| **Wikipedia Random** | `https://en.wikipedia.org/api/rest_v1/page/random/summary` | Article summaries | No key required |
| **Wikipedia Featured** | `https://en.wikipedia.org/api/rest_v1/feed/featured/{yyyy}/{mm}/{dd}` | Daily featured content | No key required |
| **This Day in History** | `https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{m}/{d}` | Historical events | No key required |
| **Numbers API** | `http://numbersapi.com/random/trivia` | Number facts | No key required |
| **Useless Facts** | `https://uselessfacts.jsph.pl/api/v2/facts/random` | Fun facts | No key required |
| **Open Trivia DB** | `https://opentdb.com/api.php?amount=50&type=multiple` | Trivia questions | No key required |
| **NewsAPI** | `https://newsapi.org/v2/top-headlines` | News articles | Free tier: 100 req/day |
| **arXiv API** | `http://export.arxiv.org/api/query` | Scientific papers | No key required |

**Recommended primary source for "fun facts":** Wikipedia Random + Numbers API + Useless Facts (all free, no API key, no rate limit issues).

**Content quality gate (using existing Claude integration):**

```python
QUALITY_GATE_PROMPT = """
Review this potential podcast source material.
Return JSON: {"suitable": true|false, "reason": "..."}

Criteria for SUITABLE:
- Contains at least 3 distinct facts or interesting concepts
- Subject matter is neutral/educational (no violence, politics, controversy)
- Written at a general audience level

Criteria for NOT SUITABLE:
- Too short (< 200 words)
- Primarily numerical data (stock prices, sports scores)
- Highly localized or time-sensitive content
- Emotionally charged topics (war, crime, disaster)
"""
```

---

## 8. Voice Characteristics — "Boring" Delivery

### What Exists

This is the strongest dimension of the existing system. The voice tuning is specifically engineered for sleep-friendly delivery:

**ElevenLabs Parameters (from `app/tts.py`):**
- `style=0.10` — near-zero expressiveness (this is the primary "boring" dial)
- `stability=0.80` — high stability = consistent, predictable cadence
- `use_speaker_boost=False` — no projection, keeps energy low
- `similarity_boost=0.75` — moderate adherence to voice character

**LLM Script Prompt (from `app/script_generator.py::EXPAND_SYSTEM`):**
- "Calm, even tone. Natural spoken language. Steady cadence."
- "No ellipsis. No rhetorical questions. No humor. No emphasis spikes."
- "No section creates anticipation. No sharp transitions."
- "Content becomes slightly less structured toward the end."
- "Listener can drop in or out at any point."
- Ending rule: "No summary. No closing phrase. End mid-thought."

**Default Voice:** Nicole (ASMR whispery) — specifically selected over the earlier default (Rachel) for being more sleep-appropriate.

### What Could Be Improved

**Speed reduction:** The current default `speed=1.0` is natural speaking pace. For sleep content, reducing to `speed=0.85` would slow delivery by 15% — a subtle but meaningful difference for helping listeners drift off. This should be the default, not an option.

**Pause injection:** ElevenLabs supports SSML `<break>` tags and voice marks for natural pauses. Adding a post-processing step to insert `... ` (ellipsis spaces) or `<break time="1s"/>` between paragraphs would improve the sleep-aid quality. However, the current prompt explicitly bans ellipsis — the solution is to use ElevenLabs voice marks instead, keeping the text clean.

**Breath sounds:** ElevenLabs' `add_voice_effects` endpoint can insert realistic breathing between phrases. This adds natural pacing without text modification.

---

## 9. Quality Control

### What Exists

The test suite is comprehensive and well-structured:

| File | Tests | Scope |
|------|-------|-------|
| `tests/test_example.py` | 7 | Integration: synthesize EN/PL/ES, edge cases |
| `tests/test_voice_selection.py` | 11 | Voice ID pass-through, defaults, fallback |
| `tests/test_db.py` | 15 | Sessions, episodes, jobs CRUD + expiry |
| `tests/test_localization.py` | 10 | Two-stage translation pipeline |
| `tests/test_restartable_processes.py` | 13 | Idempotency, language-aware jobs, migrations |
| `tests/conftest.py` | — | Settings cache fixture |

All external API calls (Anthropic, ElevenLabs) are mocked. The DB tests use in-memory SQLite. Tests run via `pytest tests/ -v`.

### What Is Missing

**Audio quality validation.** There is no automated check that synthesized audio:
- Has a non-zero duration (not a silent or empty file)
- Has a minimum bitrate (validates encoding didn't fail)
- Falls within an expected loudness range (not clipped or near-silent)
- Has a duration consistent with script word count

**End-to-end pipeline test.** Current integration tests hit individual endpoints but there is no single test that runs the full `source → conspect → expand → synthesize → download` flow with a real (non-mocked) backend.

**Recommendations (Priority 3):**

```python
# In tests/test_audio_quality.py
def test_audio_has_nonzero_duration(synthesized_mp3_bytes):
    from pydub import AudioSegment
    import io
    audio = AudioSegment.from_file(io.BytesIO(synthesized_mp3_bytes))
    assert len(audio) > 5000, "Audio should be > 5 seconds"

def test_audio_is_not_silent(synthesized_mp3_bytes):
    from pydub import AudioSegment
    import io
    audio = AudioSegment.from_file(io.BytesIO(synthesized_mp3_bytes))
    assert audio.dBFS > -60, "Audio appears to be silent"
```

---

## 10. Documentation & Maintenance

### What Exists

The README is excellent — 365 lines covering:
- Quick start (venv, ffmpeg, `.env` setup)
- API usage examples (`curl`, Python)
- Multi-language setup guide
- Voice tuning explanation
- Project structure diagram
- Environment variables reference table
- Session persistence architecture
- ElevenLabs API limits/pricing

Code quality is uniformly high: type hints, Pydantic validation, Loguru structured logging, comprehensive docstrings.

### What Is Missing

**Operational documentation** for running this as a production service:

- **Deployment guide:** No Docker, Kubernetes, or cloud platform (AWS, GCP, Heroku, Railway, Render) instructions
- **Monitoring:** No guidance on log aggregation (Datadog, CloudWatch, Loki)
- **Cost calculator:** ElevenLabs charges per character; Claude charges per token. A cost estimate for "one 15-minute episode" is valuable operational information
- **Database backup:** SQLite with WAL is used but no backup strategy is documented
- **Scaling:** No guidance for high-concurrency scenarios (SQLite bottleneck → PostgreSQL migration path)
- **Security:** No authentication on API endpoints; `CORS allow_origins=["*"]` is noted as needing tightening for production

---

## Prioritized Gap Remediation Roadmap

### Priority 1 — Core Autonomy (Estimated 2–3 weeks)

These are blockers for any autonomous operation:

1. **Content sourcing module** (`app/content_sources.py`)
   - Wikipedia Random/Featured article fetcher
   - This Day in History aggregator
   - Numbers API + Useless Facts integration
   - LLM-based content quality gate

2. **RSS feed generation** (new endpoint `GET /feeds/rss`)
   - RSS 2.0 with iTunes namespace extensions
   - Persistent `published_episodes` table (no TTL)
   - Show-level metadata (`show` table)

3. **ID3 tagging** (extend `app/audio_mixer.py`)
   - Embed episode title, show name, episode number, artwork
   - Requires: `pip install mutagen`

4. **Scheduler** (`app/scheduler.py` + lifespan integration)
   - APScheduler for in-process scheduling
   - Configurable content source and cadence via env vars
   - Alternatively: GitHub Actions `on: schedule:` workflow

### Priority 2 — Deployment (Estimated 3–5 days)

5. **Dockerfile** — Python 3.12-slim + ffmpeg pre-installed
6. **docker-compose.yml** — Single-command startup with volume mounts
7. **GitHub Actions CI** — Test workflow (`test.yml`)
8. **GitHub Actions CD** — Optional: deploy on merge to main

### Priority 3 — Content Quality (Estimated 1–2 weeks)

9. **Sleep-mode voice profile** — `speed=0.85, stability=0.90, style=0.05` as explicit default preset
10. **LUFS normalization** — Target -14 LUFS for platform compliance (requires `pyloudnorm`)
11. **Audio quality tests** — Duration, loudness, silence detection

### Priority 4 — Distribution (Estimated 2–4 weeks)

12. **Public file hosting** — S3/Cloudflare R2 integration for public MP3 URLs
13. **Platform submission helpers** — Spotify for Podcasters, Apple Podcasts Connect submission guides
14. **Webhook notifications** — Notify on new episode publish

### Priority 5 — Polish (Ongoing)

15. **Operational docs** — Deployment, monitoring, cost calculator
16. **Security hardening** — API key auth, CORS tightening, rate limiting
17. **Database scaling path** — PostgreSQL migration guide for high-concurrency
18. **Cost estimation tool** — Characters/tokens → USD calculator

---

## Architecture Strengths (What NOT to Change)

The following are well-designed and should be preserved:

- **Two-phase LLM pipeline** — Conspect separation from expansion is architecturally sound and cost-efficient
- **Session persistence** — SQLite with WAL + 7-day TTL is appropriate for the current scale
- **Streaming responses** — Real-time text streaming in expand/translate endpoints is excellent UX
- **Voice tuning** — ElevenLabs parameters are carefully calibrated; don't change the defaults
- **Error handling** — Comprehensive exception handling with meaningful HTTP status codes
- **Test structure** — Mocking strategy (in-memory DB, API mocks) is maintainable
- **Multi-language pipeline** — Two-stage translate → localize is linguistically correct
- **Configuration** — Environment-driven settings with `pydantic-settings` is the right pattern

---

## Conclusion

Spodkast is a **production-quality audio generation API** with well-tuned sleep-content delivery. The voice parameters, LLM prompts, and audio mixing pipeline are genuinely good. The code is clean, tested, and maintainable.

To become a **fully self-contained podcast pipeline**, five major components must be added:

| # | Component | Build or Buy | Estimated Effort |
|---|-----------|-------------|-----------------|
| 1 | Content sourcing (Wikipedia, trivia APIs) | Build | 1 week |
| 2 | RSS feed generation | Build | 3 days |
| 3 | ID3 audio tagging | Build (mutagen) | 1 day |
| 4 | Scheduler (APScheduler or GitHub Actions) | Build | 3 days |
| 5 | Public file hosting + CDN | Buy (S3/Cloudflare R2) | 2 days |

**Total MVP effort for full autonomy: 2–3 weeks.**

None of these additions require rewriting existing code — they slot in as new modules and endpoints on top of the existing well-designed foundation.
