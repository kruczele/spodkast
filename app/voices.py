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
    "Rachel": {
        "id": "21m00Tcm4TlvDq8ikWAM",
        "description": "Calm, warm, and gentle. Default Spodkast voice.",
        "style": "calm narration",
    },
    "Matilda": {
        "id": "XrExE9yKIg1WjnnlVkGX",
        "description": "Soft, friendly, and approachable. Great for bedtime stories.",
        "style": "warm storytelling",
    },
    "Alice": {
        "id": "Xb7hH8MSUJpSbSDYk0k2",
        "description": "Confident yet gentle. Good for longer articles.",
        "style": "professional calm",
    },
    "Aria": {
        "id": "9BWtsMINqrJLrRacOk9x",
        "description": "Expressive and natural. Slight warmth in the tone.",
        "style": "natural warmth",
    },
    "Bill": {
        "id": "pqHfZKP75CvOlQylNhV4",
        "description": "Deep, steady, and soothing. Great for evening reads.",
        "style": "deep calm",
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# Multilingual Voices (work for Polish, Spanish, and 27 other languages)
# ──────────────────────────────────────────────────────────────────────────────

MULTILINGUAL_VOICES = {
    "Rachel (multilingual)": {
        "id": "21m00Tcm4TlvDq8ikWAM",
        "languages": ["en", "pl", "es", "de", "fr", "it", "pt"],
        "description": "Default Spodkast voice. Works well in Polish and Spanish.",
    },
    "Charlotte": {
        "id": "XB0fDUnXU5powFXDhCwa",
        "languages": ["en", "pl", "es", "de", "fr", "sv"],
        "description": "Swedish-origin voice, very calm. Excellent for Polish narration.",
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
