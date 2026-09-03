"""
Prescription OCR pipeline.

Real, working OCR for PRINTED text via Tesseract (open-source, runs
locally, no API key). This is deliberately not a mock -- Tesseract will
genuinely read text out of an uploaded image.

Handwriting is the documented hard case (see the build plan, section 0.1:
benchmarks show handwriting OCR accuracy ranging roughly 20%-96% even for
commercial engines). This prototype does NOT claim to solve handwriting
OCR. Instead:
  1. Tesseract still runs on the image (it will pick up whatever it can).
  2. A heuristic flags the result as low-confidence / possibly-handwritten
     when Tesseract's own per-word confidence is low or very little text
     was recognized.
  3. Low-confidence / handwritten-flagged prescriptions are always routed
     to `confirmation_status = needs_review`, and the API layer requires
     an explicit patient-confirmation step before any medication becomes
     "confirmed" and can drive reminders (see prescriptions router).

To swap in a cloud vendor (Google Document AI, AWS Textract, or a
specialized handwriting model) for higher accuracy, implement the
OCRProvider interface below and select it via OCR_PROVIDER in config.
"""
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytesseract
from PIL import Image
from rapidfuzz import fuzz, process

from app.services.catalogue_match import CatalogueIndex

from app.core.config import get_settings

logger = logging.getLogger("arogya.ocr")

_settings = get_settings()
if _settings.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = _settings.TESSERACT_CMD


def _resolve_tessdata_prefix() -> str | None:
    """
    Locates the tessdata (language-file) directory.

    Explicit config wins. Otherwise, when TESSERACT_CMD points at a binary
    inside a conda-style prefix (<prefix>/Library/bin/tesseract.exe on
    Windows, <prefix>/bin/tesseract elsewhere), the language files sit at
    <prefix>/share/tessdata -- a layout Tesseract doesn't discover on its
    own, so it would otherwise die with "Error opening data file
    ./eng.traineddata" despite the binary itself running fine.
    """
    if _settings.TESSDATA_PREFIX:
        return _settings.TESSDATA_PREFIX
    if not _settings.TESSERACT_CMD:
        return None

    binary = Path(_settings.TESSERACT_CMD)
    # <prefix>/Library/bin/tesseract.exe -> <prefix>; <prefix>/bin/tesseract -> <prefix>
    for parents_up in (3, 2):
        if len(binary.parents) <= parents_up:
            continue
        candidate = binary.parents[parents_up] / "share" / "tessdata"
        if candidate.is_dir():
            return str(candidate)
    return None


_tessdata_prefix = _resolve_tessdata_prefix()
if _tessdata_prefix:
    os.environ.setdefault("TESSDATA_PREFIX", _tessdata_prefix)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FREQUENCY_PATTERNS = {
    r"\bOD\b|\bonce\s*(a\s*)?day\b|\bonce\s*daily\b": "once daily",
    r"\bBD\b|\bBID\b|\btwice\s*(a\s*)?day\b|\btwice\s*daily\b": "twice daily",
    r"\bTDS\b|\bTID\b|\bthrice\s*(a\s*)?day\b|\bthree\s*times\s*(a\s*)?day\b": "three times daily",
    r"\bQID\b|\bfour\s*times\s*(a\s*)?day\b": "four times daily",
    r"\bHS\b|\bat\s*night\b|\bbedtime\b": "at bedtime",
    r"\bSOS\b|\bas\s*needed\b|\bwhen\s*required\b": "as needed",
    r"\bstat\b": "immediately (stat)",
}

DOSAGE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s?(mg|mcg|ml|units?|IU)\b", re.IGNORECASE)
DURATION_PATTERN = re.compile(r"(?:for|x)\s?(\d+)\s?(?:days?|d\b)", re.IGNORECASE)


@dataclass
class OCRWord:
    text: str
    confidence: float


@dataclass
class OCRLine:
    text: str
    avg_confidence: float


@dataclass
class OCRResult:
    raw_text: str
    words: list[OCRWord] = field(default_factory=list)
    lines: list[OCRLine] = field(default_factory=list)
    avg_confidence: float = 0.0  # 0.0 - 1.0
    provider: str = "tesseract"


# Vision calls are bounded for the same reason chat calls are: a stalled
# request must degrade to manual entry rather than hang the upload.
VISION_CALL_TIMEOUT_MS = 40_000


class OCRUnavailableError(RuntimeError):
    """
    Raised when the OCR engine itself can't be reached (e.g. the Tesseract
    binary isn't installed on this machine). Distinct from "OCR ran and
    read nothing" -- the caller degrades to manual medicine entry rather
    than failing the whole upload, since the patient has to review and
    confirm every field by hand anyway (build plan §0.1).
    """


class OCRProvider:
    def extract(self, image_path: str) -> OCRResult:
        raise NotImplementedError


class TesseractOCRProvider(OCRProvider):
    """Real, local OCR via pytesseract. Best on printed prescription text."""

    def extract(self, image_path: str) -> OCRResult:
        try:
            return self._extract(image_path)
        except pytesseract.TesseractNotFoundError as exc:
            raise OCRUnavailableError(
                "The Tesseract OCR engine isn't installed or isn't on PATH. "
                "Install it (see README) or set TESSERACT_CMD in .env to its full path."
            ) from exc

    def _extract(self, image_path: str) -> OCRResult:
        image = Image.open(image_path)
        # image_to_data gives per-word bounding boxes + confidence + line
        # grouping (block_num/par_num/line_num), which we use both for an
        # overall confidence score (routing decision: needs_review vs.
        # auto-parsed) AND to reconstruct real visual lines -- far more
        # reliable for per-medicine extraction than guessing line breaks
        # from a flattened, space-joined string.
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        words: list[OCRWord] = []
        line_groups: dict[tuple, list[OCRWord]] = {}
        n = len(data["text"])
        for i in range(n):
            text = data["text"][i].strip()
            if not text:
                continue
            try:
                conf_val = float(data["conf"][i])
            except (TypeError, ValueError):
                conf_val = -1.0
            if conf_val < 0:
                continue  # tesseract uses -1 for non-text regions
            word = OCRWord(text=text, confidence=conf_val / 100.0)
            words.append(word)
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            line_groups.setdefault(key, []).append(word)

        lines: list[OCRLine] = []
        for key in sorted(line_groups.keys()):
            line_words = line_groups[key]
            line_text = " ".join(w.text for w in line_words)
            line_conf = sum(w.confidence for w in line_words) / len(line_words)
            lines.append(OCRLine(text=line_text, avg_confidence=line_conf))

        raw_text = "\n".join(l.text for l in lines)
        avg_conf = sum(w.confidence for w in words) / len(words) if words else 0.0
        return OCRResult(raw_text=raw_text, words=words, lines=lines, avg_confidence=avg_conf, provider="tesseract")


def get_ocr_provider() -> OCRProvider:
    settings = get_settings()
    if settings.OCR_PROVIDER in ("tesseract", "auto"):
        return TesseractOCRProvider()
    if settings.OCR_PROVIDER == "gemini":
        # Vision-only mode: the router calls extract_via_gemini_vision()
        # directly, so hand back a provider that always defers to it.
        return _UnavailableOCRProvider("OCR_PROVIDER=gemini: using Gemini vision instead of Tesseract.")
    raise NotImplementedError(
        f"OCR_PROVIDER='{settings.OCR_PROVIDER}' is not implemented in this prototype. "
        "Implement OCRProvider for Google Document AI / AWS Textract and register it here."
    )


class _UnavailableOCRProvider(OCRProvider):
    """Stands in when local OCR is deliberately skipped (Gemini-only mode)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def extract(self, image_path: str) -> OCRResult:
        raise OCRUnavailableError(self.reason)


# ---------------------------------------------------------------------------
# Gemini vision extraction
# ---------------------------------------------------------------------------

_VISION_PROMPT = """\
You are reading a photograph of a medical prescription, which may be printed \
or handwritten, and may be in English or an Indian language.

Transcribe it and extract the prescribed medicines.

CRITICAL SAFETY RULES:
1. NEVER guess or invent a medicine name, strength, or dose. Transcribing a \
drug name wrongly is a patient-safety incident.
2. If a word is unclear, reproduce your best reading of the visible characters \
and give that medicine a LOW confidence score. Do not "correct" it into a \
plausible drug name you aren't reading.
3. If you cannot read an item at all, omit it rather than guessing.
4. Only list medicines actually written on the prescription.
5. Copy strengths exactly as written (e.g. "500mg", "5 mg", "100 units/mL").

For frequency, normalise common prescription shorthand where it is clearly \
written: OD = "once daily", BD/BID = "twice daily", TDS/TID = "three times daily", \
QID = "four times daily", HS = "at bedtime", SOS = "as needed", STAT = "immediately (stat)".

Return `overall_confidence` between 0 and 1 reflecting how legible the \
prescription was overall (handwritten and blurry -> low; clean printed -> high).
"""

_VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "raw_text": {
            "type": "string",
            "description": "Full plain-text transcription of the prescription, one item per line.",
        },
        "overall_confidence": {"type": "number"},
        "is_handwritten": {"type": "boolean"},
        "medications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Medicine name exactly as written."},
                    "dosage": {"type": "string"},
                    "frequency": {"type": "string"},
                    "duration_days": {"type": "integer"},
                    "instructions": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["name"],
            },
        },
    },
    "required": ["raw_text", "overall_confidence", "medications"],
}


def _vision_config(types, with_thinking: bool = True) -> dict:
    """
    Shared generation config for the vision calls.

    Two problems this solves:

    1. TRUNCATION. Gemini's thinking models spend part of max_output_tokens on
       hidden reasoning before emitting anything visible. With a tight budget
       the reasoning eats it and the JSON gets cut off mid-string, surfacing
       as a JSONDecodeError rather than an obvious truncation. A generous
       budget plus capped thinking avoids it.

    2. MODEL-FAMILY DRIFT. `thinking_level` is a Gemini 3.x parameter; 2.5
       models reject it at REQUEST time with a 400, which no amount of
       try/except around config construction can catch. Callers therefore
       retry with with_thinking=False -- see _call_vision.
    """
    cfg = {
        "response_mime_type": "application/json",
        "temperature": 0.0,
        "max_output_tokens": 8000,
    }
    if with_thinking:
        try:
            cfg["thinking_config"] = types.ThinkingConfig(thinking_level="low")
        except Exception:  # noqa: BLE001
            pass
    return cfg


def _salvage_truncated_json(text: str) -> dict | None:
    """
    Recovers what it can from a JSON object the model cut off mid-generation.

    Worth doing rather than discarding: the schema declares the identifying
    fields (brand, composition, strength) BEFORE the free-text ones, so a
    response truncated in a later field still contains everything the patient
    actually needs. Throwing it away and reporting "couldn't read the pack"
    when we successfully read the brand name is a worse outcome.

    Closes any dangling string, then unwinds unclosed brackets.
    """
    if not text:
        return None
    candidate = text.strip()

    # Drop a trailing partial escape that would break the close-quote.
    if candidate.endswith("\\"):
        candidate = candidate[:-1]

    # An odd number of unescaped quotes means we're inside a string.
    unescaped = len(re.findall(r'(?<!\\)"', candidate))
    if unescaped % 2:
        candidate += '"'

    # Close whatever is still open, innermost first.
    depth: list[str] = []
    in_string = False
    escape = False
    for ch in candidate:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            depth.append(ch)
        elif ch in "}]" and depth:
            depth.pop()

    candidate = candidate.rstrip().rstrip(",")
    candidate += "".join("}" if b == "{" else "]" for b in reversed(depth))

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _call_vision(client, types, model_name: str, parts: list, schema: dict):
    """
    Runs one vision request, transparently retrying without thinking_config
    when the model's family doesn't accept it.
    """
    for with_thinking in (True, False):
        try:
            return client.models.generate_content(
                model=model_name,
                contents=parts,
                config=types.GenerateContentConfig(
                    **_vision_config(types, with_thinking), response_schema=schema
                ),
            )
        except Exception as exc:  # noqa: BLE001
            unsupported = "thinking" in str(exc).lower() and "not supported" in str(exc).lower()
            if with_thinking and unsupported:
                logger.debug("%s rejects thinking_level; retrying without it", model_name)
                continue
            raise
    raise RuntimeError("unreachable")


_PACK_PROMPT = """\
You are reading a photograph of a MEDICINE PACKAGE — a tablet strip, a bottle \
label, a carton, or a tube — not a prescription.

Extract what is printed on the pack.

CRITICAL SAFETY RULES:
1. NEVER guess a medicine name or strength. Report only what you can actually \
read on the packaging.
2. If the photo is blurry, angled, or the text is cut off, say so via a LOW \
confidence score rather than filling in a plausible answer.
3. Do not infer the generic name from the brand unless the composition is \
actually printed on the pack (it usually is, in small print).
4. Indian packs commonly print the brand name large and the composition \
underneath in smaller text — read BOTH.

Fields to look for:
  • brand_name        — the large trade name, e.g. "Dolo 650", "Augmentin 625"
  • composition       — active ingredient(s), e.g. "Paracetamol IP 650mg"
  • strength          — e.g. "650mg", "5mg", "100 units/mL"
  • manufacturer      — e.g. "Micro Labs Ltd"
  • form              — tablet / capsule / syrup / injection / inhaler / cream
  • expiry            — as printed, e.g. "08/2027". Null if not visible.
  • batch             — batch/lot number if visible, else null.
  • mrp               — printed MRP in rupees as a number, else null.
  • warnings          — any warning text printed on the pack, e.g. \
"Schedule H", "Keep out of reach of children".

Set `confidence` between 0 and 1 for how clearly you could read the pack.
Set `is_medicine_pack` false if this photo is clearly NOT a medicine package \
(a prescription, a person, a random object) so the app can tell the user.
"""

_PACK_SCHEMA = {
    "type": "object",
    "properties": {
        "is_medicine_pack": {"type": "boolean"},
        "confidence": {"type": "number"},
        "brand_name": {"type": "string"},
        "composition": {"type": "string"},
        "strength": {"type": "string"},
        "manufacturer": {"type": "string"},
        "form": {"type": "string"},
        "expiry": {"type": "string"},
        "batch": {"type": "string"},
        "mrp": {"type": "number"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        # Hard-capped on purpose. Left open-ended, the model transcribes every
        # word of regulatory small print on the pack and blows the output
        # budget, truncating the JSON mid-string -- which loses the fields
        # that actually matter. The identifying fields are declared above it
        # so they survive even a truncated response.
        "raw_text": {
            "type": "string",
            "description": "Key visible text only. MAXIMUM 200 characters. Do not transcribe fine print.",
        },
    },
    "required": ["is_medicine_pack", "confidence"],
}


def identify_medicine_from_pack(image_path: str, db) -> dict:
    """
    Reads a photo of a medicine PACK (strip, bottle, carton) and returns the
    printed details plus a fuzzy match against the curated drug database.

    This is the fallback when a prescription itself can't be read: the pack in
    the patient's hand is often far more legible than a doctor's handwriting,
    and it carries the composition in print. The patient still confirms every
    field before anything is saved -- pack reading is a DRAFT, exactly like
    prescription OCR.
    """
    settings = get_settings()
    if not settings.GOOGLE_API_KEY:
        raise OCRUnavailableError("Reading a medicine pack needs GOOGLE_API_KEY to be set.")

    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError as exc:
        raise OCRUnavailableError("Pack reading requires the 'google-genai' package.") from exc

    image_bytes = Path(image_path).read_bytes()
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"

    # Bounded like the chatbot's call: an unresponsive vision request would
    # otherwise leave a prescription upload hanging with no way to fall back
    # to manual entry.
    client = genai.Client(
        api_key=settings.GOOGLE_API_KEY,
        http_options=types.HttpOptions(timeout=VISION_CALL_TIMEOUT_MS),
    )
    models_to_try = [settings.GEMINI_VISION_MODEL] + [
        m.strip() for m in (settings.GEMINI_FALLBACK_MODELS or "").split(",") if m.strip()
    ]

    payload: dict | None = None
    last_error: Exception | None = None
    for model_name in models_to_try:
        try:
            response = _call_vision(
                client,
                types,
                model_name,
                [types.Part.from_bytes(data=image_bytes, mime_type=mime), _PACK_PROMPT],
                _PACK_SCHEMA,
            )
            text = (response.text or "").strip()
            if not text:
                continue
            payload = json.loads(text)
            break
        except json.JSONDecodeError as exc:
            # Truncated output: try to salvage the leading fields rather than
            # discarding a response whose brand name we already read.
            salvaged = _salvage_truncated_json(text)
            if salvaged:
                logger.warning(
                    "Pack read on %s was truncated; salvaged %d field(s)",
                    model_name, len(salvaged),
                )
                payload = salvaged
                break
            last_error = exc
            logger.warning("Pack read on %s returned unsalvageable JSON: %s", model_name, exc)
            continue
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("Pack read failed on %s: %s", model_name, str(exc)[:180])
            continue

    if payload is None:
        raise OCRUnavailableError(f"Could not read the pack. Last error: {last_error}")

    # Match the printed name/composition against the curated database so the
    # rest of the app (safety screening, prices, reminders) can key off a
    # canonical drug id rather than free text off a photo.
    known = _load_known_drug_names(db)
    choices = [n for n, _ in known]
    search_terms = [
        payload.get("brand_name") or "",
        payload.get("composition") or "",
    ]

    best_id = best_name = None
    best_score = 0.0
    if choices:
        for term in search_terms:
            if not term.strip():
                continue
            match = process.extractOne(term, choices, scorer=fuzz.token_set_ratio, score_cutoff=70)
            if match and match[1] > best_score:
                best_score = match[1]
                best_id = known[match[2]][1]
                best_name = match[0]

    generic_name = None
    if best_id:
        from app.models.models import DrugKnowledge

        row = db.query(DrugKnowledge).filter(DrugKnowledge.id == best_id).first()
        generic_name = row.generic_name if row else best_name

    return {
        "is_medicine_pack": bool(payload.get("is_medicine_pack", True)),
        "confidence": round(float(payload.get("confidence") or 0.0), 2),
        "brand_name": payload.get("brand_name") or None,
        "composition": payload.get("composition") or None,
        "strength": payload.get("strength") or None,
        "manufacturer": payload.get("manufacturer") or None,
        "form": payload.get("form") or None,
        "expiry": payload.get("expiry") or None,
        "batch": payload.get("batch") or None,
        "mrp": payload.get("mrp"),
        "warnings": payload.get("warnings") or [],
        "raw_text": payload.get("raw_text") or "",
        "matched_drug_id": best_id,
        "matched_generic_name": generic_name,
        "match_score": round(best_score / 100.0, 2) if best_score else None,
    }


def extract_via_gemini_vision(image_path: str, db) -> tuple[OCRResult, list["ExtractedMed"]]:
    """
    Sends the prescription image to a vision-capable Gemini model and returns
    (OCRResult, structured medications).

    This is the fallback for the case Tesseract genuinely can't serve:
    handwriting. Per build plan §0.1, handwritten prescriptions are the hard,
    unsafe case -- a vision LLM reads them far better than Tesseract, but it
    can still misread, so the result is treated exactly like any other OCR
    output: it flows into the mandatory patient-confirmation screen and never
    auto-confirms.

    Extracted names are fuzzy-matched back to the curated DrugKnowledge table
    so the rest of the app (storage notes, price comparison) still works off
    canonical drug ids rather than free text from the model.
    """
    settings = get_settings()
    if not settings.GOOGLE_API_KEY:
        raise OCRUnavailableError("Gemini vision needs GOOGLE_API_KEY to be set.")

    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError as exc:
        raise OCRUnavailableError("Gemini vision requires the 'google-genai' package.") from exc

    image_bytes = Path(image_path).read_bytes()
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"

    # Bounded like the chatbot's call: an unresponsive vision request would
    # otherwise leave a prescription upload hanging with no way to fall back
    # to manual entry.
    client = genai.Client(
        api_key=settings.GOOGLE_API_KEY,
        http_options=types.HttpOptions(timeout=VISION_CALL_TIMEOUT_MS),
    )
    models_to_try = [settings.GEMINI_VISION_MODEL] + [
        m.strip() for m in (settings.GEMINI_FALLBACK_MODELS or "").split(",") if m.strip()
    ]

    payload: dict | None = None
    last_error: Exception | None = None

    for model_name in models_to_try:
        try:
            response = _call_vision(
                client,
                types,
                model_name,
                [types.Part.from_bytes(data=image_bytes, mime_type=mime), _VISION_PROMPT],
                _VISION_SCHEMA,
            )
            text = (response.text or "").strip()
            if not text:
                continue
            payload = json.loads(text)
            if model_name != settings.GEMINI_VISION_MODEL:
                logger.info("Gemini vision used fallback model %s", model_name)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("Gemini vision model %s failed: %s", model_name, str(exc)[:200])
            continue

    if payload is None:
        raise OCRUnavailableError(f"Gemini vision failed for all models. Last error: {last_error}")

    raw_text = (payload.get("raw_text") or "").strip()
    confidence = float(payload.get("overall_confidence") or 0.0)

    known = _load_known_drug_names(db)
    choices = [n for n, _ in known]

    meds: list[ExtractedMed] = []
    seen: set[str] = set()

    for item in payload.get("medications") or []:
        name = (item.get("name") or "").strip()
        if not name:
            continue

        drug_id = generic_name = None
        score = None
        if choices:
            match = process.extractOne(name, choices, scorer=fuzz.token_set_ratio, score_cutoff=72)
            if match:
                matched_name, raw_score, idx = match
                drug_id = known[idx][1]
                score = round(raw_score / 100.0, 2)
                from app.models.models import DrugKnowledge

                row = db.query(DrugKnowledge).filter(DrugKnowledge.id == drug_id).first()
                generic_name = row.generic_name if row else matched_name

        # Deduplicate on the canonical drug when we matched one, otherwise on
        # the literal name, so two unmatched handwritten items both survive.
        dedupe_key = drug_id or name.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        duration = item.get("duration_days")
        meds.append(
            ExtractedMed(
                raw_name=name,
                matched_drug_id=drug_id,
                matched_generic_name=generic_name,
                match_score=score,
                dosage=(item.get("dosage") or None),
                frequency=(item.get("frequency") or None),
                duration_days=int(duration) if isinstance(duration, (int, float)) and duration else None,
                instructions=(item.get("instructions") or None),
            )
        )

    ocr_result = OCRResult(
        raw_text=raw_text,
        words=[OCRWord(text=w, confidence=confidence) for w in raw_text.split()],
        lines=[OCRLine(text=l, avg_confidence=confidence) for l in raw_text.splitlines() if l.strip()],
        avg_confidence=confidence,
        provider="gemini_vision",
    )
    return ocr_result, meds


# ---------- Structured extraction ----------

@dataclass
class ExtractedMed:
    raw_name: str
    matched_drug_id: str | None
    matched_generic_name: str | None
    match_score: float | None
    dosage: str | None
    frequency: str | None
    duration_days: int | None
    instructions: str | None
    # Set when the line matched the bulk brand catalogue rather than (or as
    # well as) the curated knowledge base. formulation_key drives price
    # comparison; catalogue_unit_price is the prescribed brand's own cost per
    # dose, which is the only honest baseline for "you could save X".
    composition: str | None = None
    formulation_key: str | None = None
    catalogue_price_inr: float | None = None
    catalogue_unit_price: float | None = None
    catalogue_product_name: str | None = None


def _load_known_drug_names(db) -> list[tuple[str, str]]:
    """Returns list of (searchable_name, drug_id) for fuzzy matching, covering both generic and brand names."""
    from app.models.models import DrugKnowledge

    pairs: list[tuple[str, str]] = []
    for drug in db.query(DrugKnowledge).all():
        pairs.append((drug.generic_name, drug.id))
        try:
            for brand in json.loads(drug.brand_names or "[]"):
                pairs.append((brand, drug.id))
        except json.JSONDecodeError:
            pass
    return pairs


# ---------- Bulk brand catalogue ----------
#
# The curated knowledge base knows a few dozen drugs. The imported catalogue
# knows a quarter of a million Indian brand names (see
# scripts/import_indian_medicines.py). Matching a prescription against both
# means a real brand like "Abiros CA" resolves even though no pharmacist ever
# hand-curated it -- at the cost of a wider pool, so this half of the search
# uses a stricter cutoff to keep spurious hits down.

# (name, product_id, drug_id_or_None, composition). Built once per process:
# 246k rows is a second of database work, and prescriptions arrive far more
# often than the catalogue changes. Call _reset_product_catalogue() after
# re-importing.
_PRODUCT_CACHE: list[tuple[str, str, str | None, str | None]] | None = None
_PRODUCT_INDEX: CatalogueIndex | None = None
PRODUCT_MATCH_CUTOFF = 82


def _reset_product_catalogue() -> None:
    global _PRODUCT_CACHE, _PRODUCT_INDEX
    _PRODUCT_CACHE = None
    _PRODUCT_INDEX = None


def _load_product_catalogue(db) -> list[tuple[str, str, str | None, str | None]]:
    global _PRODUCT_CACHE
    if _PRODUCT_CACHE is not None:
        return _PRODUCT_CACHE
    from app.models.models import MedicineProduct

    rows = (
        db.query(
            MedicineProduct.name,
            MedicineProduct.id,
            MedicineProduct.drug_id,
            MedicineProduct.composition,
        )
        .filter(MedicineProduct.is_discontinued.is_(False))
        .all()
    )
    _PRODUCT_CACHE = [(r[0], r[1], r[2], r[3]) for r in rows]
    return _PRODUCT_CACHE


def _load_product_index(db) -> CatalogueIndex:
    global _PRODUCT_INDEX
    if _PRODUCT_INDEX is None:
        _PRODUCT_INDEX = CatalogueIndex([row[0] for row in _load_product_catalogue(db)])
    return _PRODUCT_INDEX


def extract_frequency(line: str) -> str | None:
    for pattern, label in FREQUENCY_PATTERNS.items():
        if re.search(pattern, line, re.IGNORECASE):
            return label
    return None


def extract_structured_medications(raw_text: str, db) -> list[ExtractedMed]:
    """
    Heuristic, line-oriented extraction: for each visual line of OCR text
    (as grouped by Tesseract's own line detection -- see OCRLine), fuzzy-
    match against known drug names (generic + brand) from the curated
    knowledge base, then pull dosage/frequency/duration via regex from the
    same line. This is intentionally simple -- good enough to demonstrate
    the pipeline end-to-end on clean printed prescriptions; a production
    system would use a proper medical NER model.

    `raw_text` is expected to be newline-joined per visual line (see
    TesseractOCRProvider.extract). A caller passing a flat, space-joined
    string still works, just with lower recall, since it falls back to
    treating the whole text as one "line".
    """
    from app.models.models import DrugKnowledge, MedicineProduct

    known = _load_known_drug_names(db)
    catalogue = _load_product_catalogue(db)
    if not known and not catalogue:
        return []
    choices = [n for n, _ in known]
    product_index = _load_product_index(db) if catalogue else None

    results: list[ExtractedMed] = []
    seen_keys: set[str] = set()

    candidate_lines = [l for l in raw_text.split("\n") if l.strip()]
    if not candidate_lines:
        candidate_lines = [raw_text]

    for line in candidate_lines:
        line = line.strip()
        if not line:
            continue

        curated_match = (
            process.extractOne(line, choices, scorer=fuzz.token_set_ratio, score_cutoff=72)
            if choices
            else None
        )
        # The catalogue pool is ~5,000x larger than the curated set, so it is
        # searched through a stem index rather than scored end to end -- see
        # catalogue_match, which is where the precision guards live.
        product_match = (
            product_index.best(line, cutoff=PRODUCT_MATCH_CUTOFF) if product_index else None
        )

        # Curated wins ties: it is the only source with contraindications,
        # interactions and pregnancy data behind it.
        use_product = bool(product_match) and (
            not curated_match or product_match.score > curated_match[1]
        )

        product = None
        # Set when a combination product provides a better label than the
        # single curated molecule that won the name match.
        label_from_product = False
        if use_product:
            score = product_match.score
            product_name, product_id, drug_id, _composition = catalogue[product_match.index]
            product = db.query(MedicineProduct).filter(MedicineProduct.id == product_id).first()
            matched_name = product_name
        elif curated_match:
            matched_name, score, idx = curated_match
            drug_id = known[idx][1]
            # The curated entry won on name, but the catalogue may still know
            # which strength and pack this actually is -- "Augmentin" is a
            # curated brand, "Augmentin 625 Duo Tablet" is the thing on the
            # prescription. Borrow it for pricing when it agrees on the drug,
            # so the comparison is against 625mg and not against whatever
            # strength happens to be most common.
            if product_match is not None:
                _n, candidate_id, candidate_drug_id, _c = catalogue[product_match.index]
                if candidate_drug_id in (None, drug_id):
                    product = (
                        db.query(MedicineProduct)
                        .filter(MedicineProduct.id == candidate_id)
                        .first()
                    )
                    # A line written generically -- "Nimesulide 100mg +
                    # Paracetamol 325mg" -- matches the curated single molecule
                    # "Paracetamol" perfectly, because the curated name is a
                    # subset of the line. Labelling the row "Paracetamol" then
                    # attaches the combination's banned-drug warning to one of
                    # its ingredients, which reads as "your paracetamol is
                    # banned". When the borrowed product names more molecules
                    # than the curated drug does, it is the better label.
                    if product is not None and (product.composition_key or "").count("+") >= 1:
                        matched_name = product.name
                        label_from_product = True
        else:
            continue

        generic_name = None
        if drug_id and not label_from_product:
            drug = db.query(DrugKnowledge).filter(DrugKnowledge.id == drug_id).first()
            generic_name = drug.generic_name if drug else None
        if not generic_name and product is not None:
            # No curated entry: the composition is the most specific true thing
            # we can name this medicine by.
            generic_name = product.composition

        # Dedupe on the curated drug when there is one, else on the composition,
        # so two brands of the same molecule on one prescription collapse into
        # one row rather than reading as a duplicate-therapy warning.
        # Deduped on the curated drug normally, but on the composition when a
        # combination borrowed a single-molecule drug_id -- otherwise a plain
        # "Paracetamol 650mg" line later on the same prescription collapses
        # into the combination row and disappears.
        dedupe_key = (
            (product.composition_key if product is not None else matched_name)
            if (label_from_product or not drug_id)
            else drug_id
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        dosage_match = DOSAGE_PATTERN.search(line)
        duration_match = DURATION_PATTERN.search(line)

        results.append(
            ExtractedMed(
                raw_name=matched_name,
                matched_drug_id=drug_id,
                matched_generic_name=generic_name,
                match_score=round(score / 100.0, 2),
                dosage=f"{dosage_match.group(1)}{dosage_match.group(2)}" if dosage_match else None,
                frequency=extract_frequency(line),
                duration_days=int(duration_match.group(1)) if duration_match else None,
                instructions=line,
                composition=product.composition if product is not None else None,
                formulation_key=product.formulation_key if product is not None else None,
                catalogue_price_inr=product.price_inr if product is not None else None,
                catalogue_unit_price=(
                    (product.price_per_unit or product.price_inr) if product is not None else None
                ),
                catalogue_product_name=product.name if product is not None else None,
            )
        )

    return results
