"""
Translation / multilingual service.

Interface: `translate(text, target_lang, source_lang="en") -> str`.

- "mock" provider (default, no credentials needed): looks up a small
  bundled phrase dictionary for known UI/medical phrases, and otherwise
  returns the original text tagged with the requested language so callers
  and UI can clearly see when a real translation wasn't available.
- "bhashini" provider: placeholder for India's national language AI
  platform (https://bhashini.gov.in) -- free government APIs for
  translation, ASR, and TTS across Indian languages. Wire in with
  BHASHINI_API_KEY once you have pipeline/model IDs from their console.
- "google" provider: placeholder for Google Cloud Translation API.

Swap providers via TRANSLATION_PROVIDER in config/.env -- no caller code
changes needed.
"""
import json
from pathlib import Path

from app.core.config import get_settings

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "bn": "Bengali",
    "mr": "Marathi",
    "gu": "Gujarati",
}

_PHRASE_DICT_PATH = DATA_DIR / "phrase_dictionary.json"


def _load_phrase_dict() -> dict:
    if _PHRASE_DICT_PATH.exists():
        return json.loads(_PHRASE_DICT_PATH.read_text(encoding="utf-8"))
    return {}


_PHRASES = _load_phrase_dict()


class TranslationService:
    def translate(self, text: str, target_lang: str, source_lang: str = "en") -> str:
        raise NotImplementedError

    def language_list(self) -> dict:
        return SUPPORTED_LANGUAGES


class MockTranslationService(TranslationService):
    def translate(self, text: str, target_lang: str, source_lang: str = "en") -> str:
        if target_lang == source_lang or target_lang not in SUPPORTED_LANGUAGES:
            return text
        lang_dict = _PHRASES.get(target_lang, {})
        if text in lang_dict:
            return lang_dict[text]
        # No canned translation available for this exact string in the
        # prototype's small dictionary. Being explicit about this beats
        # silently returning English text as if it were translated.
        return f"{text} [{SUPPORTED_LANGUAGES[target_lang]} translation pending — connect a real provider]"


class BhashiniTranslationService(TranslationService):
    """Placeholder. Requires BHASHINI_API_KEY + pipeline/model config."""

    def translate(self, text: str, target_lang: str, source_lang: str = "en") -> str:
        raise NotImplementedError(
            "Bhashini integration not wired up in this prototype. "
            "Register at https://bhashini.gov.in, obtain pipeline IDs, "
            "and implement the ULCA inference API call here."
        )


def get_translation_service() -> TranslationService:
    settings = get_settings()
    if settings.TRANSLATION_PROVIDER == "bhashini" and settings.BHASHINI_API_KEY:
        return BhashiniTranslationService()
    return MockTranslationService()
