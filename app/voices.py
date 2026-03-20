"""
ElevenLabs Voice Reference for Spodkast.

A curated list of voices well-suited for calm "goodnight read" narration.
Use these IDs in your .env file (VOICE_ID_EN, VOICE_ID_PL, etc.).

All voices below support the eleven_multilingual_v2 model.
"""

# ──────────────────────────────────────────────────────────────────────────────
# Recommended English Voices (calm / warm / soothing)
# ──────────────────────────────────────────────────────────────────────────────

ENGLISH_VOICES = {
    # Free-tier API compatible voices (tested and confirmed working)
    "Sarah": {
        "id": "EXAVITQu4vr4xnSDxMaL",
        "description": "Mature, reassuring, confident. Default Spodkast voice. Free tier compatible.",
        "style": "calm narration",
        "free_tier": True,
    },
    "Matilda": {
        "id": "XrExE9yKIg1WjnnlVkGX",
        "description": "Knowledgeable, professional. Great for bedtime article narration.",
        "style": "warm storytelling",
        "free_tier": True,
    },
    "Alice": {
        "id": "Xb7hH8MSUJpSbSDYk0k2",
        "description": "Clear, engaging educator. Good for longer articles.",
        "style": "professional calm",
        "free_tier": True,
    },
    "Lily": {
        "id": "pFZP5JQG7iQjIQuC4Bku",
        "description": "Velvety actress. Very soothing for sleepy-time reads.",
        "style": "velvet warmth",
        "free_tier": True,
    },
    "George": {
        "id": "JBFqnCBsd6RMkjVDRZzb",
        "description": "Warm, captivating storyteller. Great male voice for calm narration.",
        "style": "deep calm",
        "free_tier": True,
    },
    # Paid-tier only voices (paid API subscription required)
    "Rachel": {
        "id": "21m00Tcm4TlvDq8ikWAM",
        "description": "Calm, warm, gentle. Popular choice for goodnight reads. Requires paid plan.",
        "style": "calm narration",
        "free_tier": False,
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# Multilingual Voices (work for Polish, Spanish, and 27 other languages)
# ──────────────────────────────────────────────────────────────────────────────

MULTILINGUAL_VOICES = {
    # Free-tier API compatible multilingual voices (tested EN, PL, ES)
    "Sarah (multilingual)": {
        "id": "EXAVITQu4vr4xnSDxMaL",
        "languages": ["en", "pl", "es", "de", "fr", "it", "pt"],
        "description": "Default Spodkast voice. Works well in Polish and Spanish. Free tier compatible.",
        "free_tier": True,
    },
    "George (multilingual)": {
        "id": "JBFqnCBsd6RMkjVDRZzb",
        "languages": ["en", "pl", "es", "de", "fr", "it"],
        "description": "Warm, captivating storyteller. Excellent for Polish narration.",
        "free_tier": True,
    },
    # Paid-tier only
    "Rachel (multilingual)": {
        "id": "21m00Tcm4TlvDq8ikWAM",
        "languages": ["en", "pl", "es", "de", "fr", "it", "pt"],
        "description": "Popular calm voice for multilingual narration. Requires paid plan.",
        "free_tier": False,
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# Voice selection helper
# ──────────────────────────────────────────────────────────────────────────────

def list_voices_for_language(language_code: str) -> list[dict]:
    """
    Return voices suitable for a given language code.
    Checks both English voices (for 'en') and multilingual voices.
    """
    results = []

    if language_code == "en":
        for name, info in ENGLISH_VOICES.items():
            results.append({"name": name, **info})

    for name, info in MULTILINGUAL_VOICES.items():
        if language_code in info.get("languages", []):
            results.append({"name": name, **info})

    return results
