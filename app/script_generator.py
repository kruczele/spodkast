"""
LLM-based podcast script generator.
Two-phase pipeline:
  1. generate_conspect()  — fast; parses source once, returns episode plan.
  2. expand_episode()     — per episode; writes full script from plan only.
"""

import json
from dataclasses import dataclass

import anthropic
from loguru import logger


# ──────────────────────────────────────────────────────────────────────────────
# Phase 1 — Conspect generation
# ──────────────────────────────────────────────────────────────────────────────

CONSPECT_SYSTEM = """\
# ROLE
You are planning a set of sleep-friendly podcast episodes from source material.

# TASK
Read the source and produce an episode plan for up to 8 episodes.

# OUTPUT FORMAT
Return a single JSON object — no markdown fences, no extra text.

{
  "episodes": [
    {
      "index": 1,
      "title": "short calm title",
      "summary": "3-5 sentences describing what this episode covers and the key ideas to expand on"
    }
  ],
  "operator_message": null
}

If the source does not contain enough material for 8 episodes, produce as many as
viable and set operator_message to a plain-text explanation of what is missing.

# EPISODE RULES
- Each episode covers a distinct sub-topic or angle
- No episode should reference another ("in the previous episode...")
- Titles are calm and descriptive, not clickbait
- Summaries are dense planning notes — enough to write a 1500-word script from\
"""


@dataclass
class EpisodeOutline:
    index: int
    title: str
    summary: str


@dataclass
class ConspectResult:
    episodes: list[EpisodeOutline]
    operator_message: str | None


def generate_conspect(source_text: str, api_key: str) -> ConspectResult:
    """
    Phase 1: Parse source once, return a lightweight episode plan.
    Fast — output is short JSON.
    """
    client = anthropic.Anthropic(api_key=api_key)
    logger.info(f"Generating conspect from {len(source_text)} chars")

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=CONSPECT_SYSTEM,
            messages=[{"role": "user", "content": source_text}],
        )
        raw = next(block.text for block in message.content if block.type == "text")
        data = json.loads(raw)

        episodes = [
            EpisodeOutline(index=ep["index"], title=ep["title"], summary=ep["summary"])
            for ep in data["episodes"]
        ]
        operator_message = data.get("operator_message") or None
        logger.info(f"Conspect ready: {len(episodes)} episode(s)")
        return ConspectResult(episodes=episodes, operator_message=operator_message)

    except json.JSONDecodeError as e:
        raise RuntimeError(f"Conspect output was not valid JSON: {e}")
    except anthropic.AuthenticationError:
        raise RuntimeError("Invalid Anthropic API key")
    except anthropic.RateLimitError:
        raise RuntimeError("Anthropic API rate limit exceeded")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise RuntimeError("Failed to connect to Anthropic API")


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — Per-episode expansion
# ──────────────────────────────────────────────────────────────────────────────

EXPAND_SYSTEM = """\
# ROLE
Write a single calm, low-stimulation spoken script for a sleep-friendly podcast episode.

# INPUT
You will receive:
1. The full episode plan (all episodes) for coherence context.
2. The specific episode to write, marked with *** TARGET ***.

# OUTPUT
Plain text only. 1500–2000 words. No headers, no formatting.
Return only the script — nothing else.

---

# STRUCTURE

## Opening (0–20s)
- 1–2 sentences. State the topic softly. Allow the listener to disengage.

## Main body (~80%)
- Continuous explanation. 3–4 loosely connected segments.
- Segments must be independent — no narrative arcs or buildup.

## Final phase (~20%)
- Slightly slower pacing. Increased repetition. Simpler phrasing.
- No explicit transition into this phase.

## Ending
- No summary. No closing phrase. End mid-thought.

---

# STYLE
- Calm, even tone. Natural spoken language. Steady cadence.
- No ellipsis (...). No rhetorical questions. No humor. No emphasis spikes.

---

# CONTENT RULES
- Neutral, descriptive subject matter. Low emotional intensity.
- No conflict or tension. No surprising or "wow" framing.

---

# QUALITY CHECK
- Listener can drop in or out at any point.
- No section creates anticipation. No sharp transitions.
- Content becomes slightly less structured toward the end.\
"""


LANGUAGE_NAMES: dict[str, str] = {
    "pl": "Polish",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "ja": "Japanese",
    "zh": "Chinese",
}


TRANSLATE_SYSTEM_TEMPLATE = """\
Translate the following podcast script to {lang_name}.
Preserve the calm, low-stimulation tone and natural spoken language style.
Return only the translated script — no headers, no notes, no extra text.\
"""

# Localization prompts per language — each one instructs the model to rewrite
# the literal translation so it reads like native prose, not translated text.
LOCALIZE_SYSTEM_TEMPLATE = """\
You are a native {lang_name} editor specialising in spoken-word content.

You will receive a podcast script that has been machine-translated from English
into {lang_name}. The translation is accurate but may read as stiff, literal, or
foreign-sounding.

Your task:
- Rewrite every sentence so it sounds natural and idiomatic in {lang_name}.
- Fix literal calques, awkward word order, and un-{lang_name} phrasing.
- Ensure rhythm and cadence feel native to {lang_name} listeners.
- Keep the meaning, structure, length, and calm sleep-friendly tone exactly as-is.
- Do NOT add, remove, or summarise content.
- Return only the rewritten script — no headers, no notes, no extra text.\
"""


def translate_script(text: str, target_language: str, api_key: str) -> str:
    """
    Stage 1 of the two-stage localization pipeline.
    Produces a direct (possibly literal) translation of *text* into *target_language*.
    Preserves the calm, spoken-word style.
    """
    lang_name = LANGUAGE_NAMES.get(target_language, target_language)
    client = anthropic.Anthropic(api_key=api_key)
    logger.info(f"[Stage 1] Translating {len(text)} chars to {lang_name}")

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=20000,
            system=TRANSLATE_SYSTEM_TEMPLATE.format(lang_name=lang_name),
            messages=[{"role": "user", "content": text}],
        )
        translated = next(block.text for block in message.content if block.type == "text")
        logger.info(f"[Stage 1] Translation complete: {len(translated)} chars")
        return translated

    except anthropic.AuthenticationError:
        raise RuntimeError("Invalid Anthropic API key")
    except anthropic.RateLimitError:
        raise RuntimeError("Anthropic API rate limit exceeded")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise RuntimeError("Failed to connect to Anthropic API")


def localize_script(translated_text: str, target_language: str, api_key: str) -> str:
    """
    Stage 2 of the two-stage localization pipeline.
    Takes the output of Stage 1 (a literal translation) and rewrites it to sound
    natural and idiomatic in *target_language* while preserving meaning and tone.
    """
    lang_name = LANGUAGE_NAMES.get(target_language, target_language)
    client = anthropic.Anthropic(api_key=api_key)
    logger.info(f"[Stage 2] Localizing {len(translated_text)} chars into native {lang_name}")

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=20000,
            system=LOCALIZE_SYSTEM_TEMPLATE.format(lang_name=lang_name),
            messages=[{"role": "user", "content": translated_text}],
        )
        localized = next(block.text for block in message.content if block.type == "text")
        logger.info(f"[Stage 2] Localization complete: {len(localized)} chars")
        return localized

    except anthropic.AuthenticationError:
        raise RuntimeError("Invalid Anthropic API key")
    except anthropic.RateLimitError:
        raise RuntimeError("Anthropic API rate limit exceeded")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise RuntimeError("Failed to connect to Anthropic API")


def translate_and_localize(text: str, target_language: str, api_key: str) -> str:
    """
    Full two-stage localization pipeline (non-streaming, synchronous).
    Stage 1: literal translation → Stage 2: idiomatic rewrite.
    Use the streaming variant in the router for real-time UI feedback.
    """
    stage1 = translate_script(text, target_language, api_key)
    return localize_script(stage1, target_language, api_key)


def expand_episode(outlines: list[EpisodeOutline], episode_index: int, api_key: str) -> str:
    """
    Phase 2: Expand a single episode from the plan.
    Full source is NOT re-sent — only the compact plan is used.
    """
    client = anthropic.Anthropic(api_key=api_key)

    plan_lines = []
    for ep in outlines:
        marker = "*** TARGET ***" if ep.index == episode_index else ""
        plan_lines.append(
            f"Episode {ep.index}: {ep.title} {marker}\n{ep.summary}"
        )
    user_content = "\n\n".join(plan_lines)

    logger.info(f"Expanding episode {episode_index} ({len(user_content)} chars input)")

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=20000,
            system=EXPAND_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        text = next(block.text for block in message.content if block.type == "text")
        logger.info(f"Episode {episode_index} expanded: {len(text)} chars")
        return text

    except anthropic.AuthenticationError:
        raise RuntimeError("Invalid Anthropic API key")
    except anthropic.RateLimitError:
        raise RuntimeError("Anthropic API rate limit exceeded")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise RuntimeError("Failed to connect to Anthropic API")
