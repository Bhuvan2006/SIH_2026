"""
Central configuration.

Every external/paid integration (OCR vendor, translation, LLM, maps, SMS)
is read from environment variables here. When a key is absent, the
corresponding service falls back to its mock/local implementation so the
whole app runs with zero paid credentials. Set the env vars in a real
deployment to switch each service to its production backend -- no code
changes required elsewhere, because callers only ever see the abstract
service interface (see app/services/*.py).
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Arogya API"
    ENV: str = "development"
    # Base URL of the FRONTEND, used to build the emergency QR link that a
    # first responder scans. Must be reachable from their phone, so in a real
    # deployment this is your public https domain, not localhost.
    PUBLIC_APP_URL: str = "http://localhost:5173"

    # --- Database ---
    # SQLite for local/dev prototype. Point DATABASE_URL at a Postgres DSN
    # in production (e.g. postgresql+psycopg2://user:pass@host/db).
    DATABASE_URL: str = "sqlite:///./arogya.db"

    # --- Auth ---
    JWT_SECRET: str = "dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7
    # In dev mode, any 6-digit OTP is accepted and the "sent" code is
    # returned in the API response so the flow is testable without SMS.
    OTP_DEV_MODE: bool = True

    # --- OCR ---
    # "tesseract"  local Tesseract only (printed text; no API calls)
    # "gemini"     Gemini vision only (handles handwriting far better)
    # "auto"       Tesseract first, then Gemini vision when Tesseract is
    #              missing, errors, or reads nothing useful. Recommended.
    # ("document_ai"/"textract" cloud vendors are not implemented here, but
    #  the OCRProvider interface in ocr_service.py is ready for them.)
    OCR_PROVIDER: str = "auto"
    OCR_LOW_CONFIDENCE_THRESHOLD: float = 0.55  # below this -> manual review
    # Vision-capable Gemini model used for prescription image extraction.
    # Falls back through GEMINI_FALLBACK_MODELS on quota errors, same as chat.
    GEMINI_VISION_MODEL: str = "gemini-2.5-flash"
    # Absolute path to tesseract.exe. Only needed on Windows if the Tesseract
    # binary isn't on PATH (e.g. a fresh install at its default location,
    # before the shell's PATH has been refreshed). Leave unset on
    # Linux/macOS or once `tesseract` is on PATH.
    TESSERACT_CMD: str | None = None
    # Directory holding the *.traineddata language files. Tesseract normally
    # finds this itself; it needs setting when the binary lives somewhere
    # non-standard (e.g. a conda env), otherwise Tesseract fails at runtime
    # with "Error opening data file ./eng.traineddata". When left unset and
    # TESSERACT_CMD points inside a conda-style layout, we derive it below.
    TESSDATA_PREFIX: str | None = None

    # --- Translation / multilingual ---
    # "mock" (small bundled dictionary) or "bhashini" / "google" (requires
    # API keys, not wired up here).
    TRANSLATION_PROVIDER: str = "mock"
    BHASHINI_API_KEY: str | None = None
    GOOGLE_TRANSLATE_API_KEY: str | None = None

    # --- Chatbot / LLM ---
    # "retrieval" (grounded template answers, no external call, always available)
    # "google"    (Gemini via GOOGLE_API_KEY — retrieval runs first as grounding context)
    # "anthropic" (requires ANTHROPIC_API_KEY)
    LLM_PROVIDER: str = "retrieval"
    ANTHROPIC_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-3.5-flash"
    # Gemini's free tier caps requests *per model per day* (currently 20), so a
    # single busy day silently knocks the chatbot back to template answers.
    # These are tried in order when the primary model returns 429/quota errors;
    # each has its own separate quota bucket. Comma-separated.
    GEMINI_FALLBACK_MODELS: str = "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3-flash-preview"
    CHAT_HISTORY_TURNS: int = 6  # past user+assistant pairs to send for conversational context

    # --- Maps / pharmacy locator ---
    # "mock" (bundled sample pharmacy list) or "google_places" (requires
    # GOOGLE_PLACES_API_KEY, not wired up here).
    PLACES_PROVIDER: str = "mock"
    GOOGLE_PLACES_API_KEY: str | None = None

    # --- Notifications ---
    # "mock" (log-only, default) or "msg91" (real SMS via MSG91's Flow API).
    NOTIFICATION_PROVIDER: str = "mock"
    # MSG91 uses DLT-compliant template ("Flow") SMS in India -- free-form
    # text isn't accepted by carriers without a pre-approved template. Create
    # a Flow in the MSG91 dashboard with one variable (e.g. body text
    # "Arogya: ##VAR1##"), then set its flow_id here.
    MSG91_AUTH_KEY: str | None = None
    MSG91_FLOW_ID: str | None = None
    MSG91_SENDER_ID: str | None = None  # 6-char DLT-registered sender ID, e.g. "AROGYA"


@lru_cache
def get_settings() -> Settings:
    return Settings()
