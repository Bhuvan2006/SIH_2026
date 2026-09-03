"""
Chatbot service — RAG-grounded answers with optional LLM rephrasing.

Architecture (unchanged from build plan §6.6):
  1. Emergency check  — short-circuits immediately, no LLM involved.
  2. RAG retrieval    — fetches curated DrugFact / DietFact records from the
                        local knowledge base. Always runs; results become the
                        grounding context for the LLM.
  3. Answer composition:
       LLM_PROVIDER="retrieval"  — deterministic template composer (no API key).
       LLM_PROVIDER="google"     — Google Gemini (GOOGLE_API_KEY required).
                                   Retrieval facts are injected first so the
                                   model can't hallucinate curated data, and
                                   Gemini's broader medical knowledge fills in
                                   questions the 24-drug local KB doesn't cover.
       LLM_PROVIDER="anthropic"  — Claude (ANTHROPIC_API_KEY required).

Safety guarantees that hold regardless of provider:
  • Emergency keywords → escalation response, LLM never called.
  • System prompt explicitly forbids diagnosis, treatment recommendations,
    and off-topic (non-medicine) answers.
  • Disclaimer appended to every non-emergency response by the router.
"""
import json
import logging
import re
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.rag.knowledge_retriever import RetrievalResult, retrieve

# Wall-clock limits on the Gemini call. Chosen so a stalled model degrades to
# the grounded retrieval answer while the patient is still waiting, instead of
# holding the request open indefinitely.
GEMINI_CALL_TIMEOUT_MS = 20_000
GEMINI_TOTAL_BUDGET_SECONDS = 45
# Below this there is not enough time left for a model to plausibly answer, so
# the remaining budget is better spent returning the retrieval answer.
MIN_ATTEMPT_MS = 6_000

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "This is general medical information, not a diagnosis or a personalized "
    "treatment plan. Always confirm with your doctor or pharmacist before "
    "starting, stopping, or changing any medication."
)

EMERGENCY_RESPONSE = (
    "This sounds like it could be a medical emergency. Please contact your "
    "local emergency services or go to the nearest hospital right away, or "
    "call a trusted person to help you immediately. I'm not able to safely "
    "help with this in a chat — please get in-person medical help now."
)

# ---------------------------------------------------------------------------
# Internal data classes
# ---------------------------------------------------------------------------

@dataclass
class Citation:
    source_id: str
    label: str


@dataclass
class ChatAnswer:
    answer: str
    citations: list[Citation]
    is_emergency_escalation: bool


# ---------------------------------------------------------------------------
# Helper: build the grounding text from RAG results
# ---------------------------------------------------------------------------

def _build_grounding_text(result: RetrievalResult) -> str:
    """
    Converts retrieved DrugFact / DietFact records into a plain-text block
    that can be injected verbatim into any LLM prompt as a grounding context.
    """
    lines: list[str] = []

    # The patient's own record goes first: when someone asks "is this safe
    # with my medicines?", their actual medicine list matters more than any
    # generic drug fact retrieved afterwards.
    if result.patient_context:
        lines.append(result.patient_context)
        lines.append("")

    if result.is_pregnancy_query:
        lines.append(
            "[NOTE] This question relates to pregnancy or breastfeeding. Pay special attention "
            "to any contraindications below that mention pregnancy, trimester, or breastfeeding, "
            "and follow the pregnancy-safety rule in your system instructions."
        )
        lines.append("")

    for fact in result.drug_facts:
        lines.append(f"[CURATED DRUG FACT — {fact.generic_name}]")
        lines.append(f"  Composition: {fact.composition}")
        if fact.storage_instructions:
            lines.append(f"  Storage: {fact.storage_instructions}")
        if fact.common_interactions:
            lines.append("  Common interactions: " + "; ".join(fact.common_interactions))
        if fact.contraindications:
            lines.append("  Contraindications: " + "; ".join(fact.contraindications))
        if fact.source_citation:
            lines.append(f"  Source: {fact.source_citation}")
        lines.append("")

    for fact in result.diet_facts:
        lines.append(f"[CURATED DIET GUIDANCE — {fact.label}]")
        lines.append("  Prefer: " + ", ".join(fact.prefer))
        lines.append("  Avoid/limit: " + ", ".join(fact.avoid))
        if fact.notes:
            lines.append(f"  Notes: {fact.notes}")
        lines.append("")

    return "\n".join(lines).strip()


def _build_citations(result: RetrievalResult) -> list[Citation]:
    citations: list[Citation] = []
    for fact in result.drug_facts:
        citations.append(
            Citation(source_id=fact.drug_id, label=f"{fact.generic_name} — {fact.source_citation}")
        )
    for fact in result.diet_facts:
        citations.append(
            Citation(
                source_id=fact.condition_key,
                label=f"Diet guidance — {fact.label} (sample curated data)",
            )
        )
    return citations


# ---------------------------------------------------------------------------
# Provider: deterministic template composer (no LLM, no API key)
# ---------------------------------------------------------------------------

def _compose_from_retrieval(query: str, result: RetrievalResult) -> tuple[str, list[Citation]]:
    if not result.drug_facts and not result.diet_facts:
        if result.is_pregnancy_query:
            return (
                "I don't have curated pregnancy-safety data for that specific medicine yet. "
                "Please don't assume it's safe — check with your obstetrician, doctor, or "
                "pharmacist before taking any medicine while pregnant or breastfeeding.",
                [],
            )
        return (
            "I don't have curated information on that in my current knowledge base yet. "
            "I'd rather not guess about medical details — please ask your doctor or pharmacist, "
            "or try rephrasing with a specific medicine or condition name.",
            [],
        )

    parts: list[str] = []
    citations = _build_citations(result)

    if result.is_pregnancy_query and result.drug_facts:
        parts.append(
            "⚠️ Pregnancy/breastfeeding safety notes from the curated medicine database:"
        )

    for fact in result.drug_facts:
        segment = [f"**{fact.generic_name}** ({fact.composition})"]
        if result.is_pregnancy_query:
            pregnancy_notes = [
                c for c in fact.contraindications
                if re.search(r"pregnan|breastfeed|lactat|trimester", c.lower())
            ]
            if pregnancy_notes:
                segment.append("⚠️ " + "; ".join(pregnancy_notes))
            else:
                segment.append(
                    "No pregnancy-specific caution is recorded for this medicine in our curated "
                    "data, but that is not the same as confirmed safety — please still check "
                    "with your doctor."
                )
        elif any(w in query.lower() for w in ["store", "storage", "temperature", "keep", "fridge", "refrigerat"]):
            if fact.storage_instructions:
                segment.append(f"Storage: {fact.storage_instructions}")
        elif any(w in query.lower() for w in ["interact", "together", "combine", "mix", "alcohol"]):
            if fact.common_interactions:
                segment.append("Watch out for: " + "; ".join(fact.common_interactions))
        else:
            if fact.storage_instructions:
                segment.append(f"Storage: {fact.storage_instructions}")
            if fact.common_interactions:
                segment.append("Common interactions: " + "; ".join(fact.common_interactions))
            if fact.contraindications:
                segment.append("Avoid if: " + "; ".join(fact.contraindications))
        parts.append(" ".join(segment))

    for fact in result.diet_facts:
        segment = [f"For **{fact.label}**:"]
        segment.append("Prefer: " + ", ".join(fact.prefer) + ".")
        segment.append("Avoid/limit: " + ", ".join(fact.avoid) + ".")
        if fact.notes:
            segment.append(fact.notes)
        parts.append(" ".join(segment))

    if result.is_pregnancy_query:
        parts.append(
            "Please do not start, stop, or continue any medicine during pregnancy or while "
            "breastfeeding without checking with your obstetrician or doctor first."
        )

    return "\n\n".join(parts), citations


# ---------------------------------------------------------------------------
# Provider: Google Gemini
# ---------------------------------------------------------------------------

_GEMINI_SYSTEM_PROMPT = """\
You are Arogya Assistant, a knowledgeable and empathetic medical-information \
assistant built into the Arogya health app for Indian patients.

Your role:
• Answer questions about medicines, dosages, drug interactions, storage, \
side effects, contraindications, and condition-related diet/lifestyle guidance.
• Provide clear, accurate, easy-to-understand information in plain language.
• Be warm and reassuring, especially for patients who may be anxious.

Hard rules you must always follow:
1. NEVER diagnose a condition or tell a patient which medicine to take or stop.
2. NEVER make up drug names, dosages, or clinical facts. If unsure, say so.
3. If the user's question is unrelated to medicine, health, or nutrition, \
politely decline and redirect: "I can only help with medicine and health \
questions. Please consult the right resource for other topics."
4. Do NOT answer questions about self-harm, obtaining prescription drugs \
illegally, or anything harmful.
5. Always remind users that your information is general and they should \
consult their doctor or pharmacist for personal medical decisions \
(the app adds a formal disclaimer automatically — keep your reminder brief).
6. PREGNANCY / BREASTFEEDING SAFETY — treat with extra care. If the user \
mentions being pregnant, trying to conceive, or breastfeeding, or asks \
whether a medicine is safe in pregnancy:
   - Prioritise any curated knowledge-base contraindications given below —
     if a medicine is flagged there as unsafe in pregnancy (e.g. certain
     trimesters), state that clearly and plainly near the top of your answer.
   - For medicines not covered in the curated knowledge base, answer from
     general medical knowledge but be conservative: many drugs considered
     routine outside pregnancy (NSAIDs, several antibiotics, ACE
     inhibitors/ARBs, statins, warfarin, retinoids, etc.) carry real risk in
     pregnancy — say so if applicable, and never state a medicine is
     "safe" in pregnancy without noting that safety depends on trimester,
     dose, and the specific clinical situation.
   - Always close a pregnancy-related answer with a clear line such as:
     "Please do not start, stop, or continue any medicine during pregnancy
     without checking with your obstetrician or doctor first."
   - If asked generally "what medicines should I avoid during pregnancy",
     you may give well-known categories (e.g. certain NSAIDs, some
     antibiotics, ACE inhibitors/ARBs, isotretinoin, warfarin) as general
     education, but frame it as general knowledge, not a personalized or
     exhaustive list, and still direct them to their doctor.

You may be given a [THIS PATIENT'S OWN RECORD] block containing the patient's \
profile, blood group, allergies, conditions, and the medicines they have \
confirmed they are taking (with dose times). Use it to answer personally and \
concretely -- "your metformin at 08:00", not "metformin is usually taken...". \
If they ask what they take, when to take it, or whether something interacts \
with their medicines, answer from that record. If the record is empty or does \
not cover the question, say so plainly rather than inventing an entry; suggest \
they add the prescription or detail to their profile. Never invent a medicine, \
allergy, or condition that is not listed there.

When curated knowledge-base facts are provided below, prioritise them \
over your general training data and do not contradict them. Clearly \
attribute information from the knowledge base when you use it.
If no curated facts are available for the question, answer from your \
general medical knowledge and indicate it is general information.

LANGUAGE: Reply in the language named in the "Reply language" line of the \
user message. If the user clearly writes in a different language, prefer the \
language they actually wrote in. Never switch language just because the \
patient has an Indian name or the topic is India-specific.
"""

_LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "bn": "Bengali",
    "mr": "Marathi",
    "gu": "Gujarati",
}


def _compose_via_google(
    query: str,
    result: RetrievalResult,
    history: list[dict] | None = None,
    language: str | None = None,
) -> tuple[str, list[Citation]]:
    """
    Calls Google Gemini. Retrieval facts are injected as grounding context.
    `history` is a list of {"role": "user"|"model", "parts": [{"text": ...}]}
    dicts representing prior turns in the session.
    """
    settings = get_settings()

    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError as exc:
        raise NotImplementedError(
            "LLM_PROVIDER=google requires the 'google-genai' package. "
            "Run: pip install google-genai"
        ) from exc

    grounding_text = _build_grounding_text(result)
    citations = _build_citations(result)

    lang_name = _LANGUAGE_NAMES.get((language or "en").lower(), "English")

    # Build the user message: inject curated facts before the actual question
    if grounding_text:
        user_content = (
            f"CURATED KNOWLEDGE BASE CONTEXT (treat as authoritative):\n"
            f"{grounding_text}\n\n"
            f"---\n"
            f"Reply language: {lang_name}\n"
            f"User question: {query}"
        )
    else:
        user_content = (
            f"(No curated facts matched this query — answer from general medical knowledge "
            f"and label it as general information.)\n\n"
            f"Reply language: {lang_name}\n"
            f"User question: {query}"
        )

    # Build conversation history for multi-turn context
    contents: list[dict] = []
    for turn in (history or []):
        contents.append(turn)
    contents.append({"role": "user", "parts": [{"text": user_content}]})

    # A hung upstream call must not hang the request. The SDK does not time
    # out by default, so a single unresponsive Gemini call left /chat/ask
    # waiting indefinitely with the user staring at a spinner -- and because
    # the loop below tries several models in turn, one slow model could hold
    # the request open for minutes. Per-call timeout plus an overall deadline
    # bounds the worst case; past it the patient gets the retrieval answer,
    # which is grounded and immediate, rather than nothing.
    client = genai.Client(
        api_key=settings.GOOGLE_API_KEY,
        http_options=types.HttpOptions(timeout=GEMINI_CALL_TIMEOUT_MS),
    )
    deadline = time.monotonic() + GEMINI_TOTAL_BUDGET_SECONDS

    # Gemini 3.x models spend part of max_output_tokens on hidden "thinking"
    # tokens before producing visible text -- at the old budget (800) that
    # reasoning alone could exhaust the budget and truncate the real answer
    # to nothing. Capping thinking to "low" and raising the budget avoids
    # that. Older SDK versions don't support thinking_level, so fall back
    # to a plain config if constructing it fails.
    config_kwargs = dict(
        system_instruction=_GEMINI_SYSTEM_PROMPT,
        max_output_tokens=3000,
        temperature=0.3,   # low temperature → consistent, factual answers
    )
    try:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="low")
    except Exception:  # noqa: BLE001
        pass

    # Try the primary model, then each fallback. Gemini's free tier meters
    # requests per model per day, so when the primary is exhausted a sibling
    # model usually still has budget -- far better than dropping the whole
    # chatbot back to template answers for the rest of the day.
    models_to_try = [settings.GEMINI_MODEL] + [
        m.strip() for m in (settings.GEMINI_FALLBACK_MODELS or "").split(",") if m.strip()
    ]

    answer = ""
    last_error: Exception | None = None

    for model_name in models_to_try:
        # Only start an attempt that can finish inside the budget. Checking
        # merely that the budget is not yet spent let a call starting at 49s
        # run its full timeout on top, so a 50s budget produced a 74s wait.
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms < MIN_ATTEMPT_MS:
            logger.warning(
                "Gemini budget of %ss exhausted; falling back to template answers",
                GEMINI_TOTAL_BUDGET_SECONDS,
            )
            break
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    **config_kwargs,
                    http_options=types.HttpOptions(
                        timeout=min(GEMINI_CALL_TIMEOUT_MS, remaining_ms)
                    ),
                ),
            )
            answer = response.text or ""
            finish_reason = (
                getattr(response.candidates[0], "finish_reason", None) if response.candidates else None
            )
            if finish_reason is not None and str(finish_reason).endswith("MAX_TOKENS") and not answer.strip():
                logger.warning(
                    "Gemini model %s hit MAX_TOKENS with no visible text; trying next model", model_name
                )
                continue
            if answer.strip():
                if model_name != settings.GEMINI_MODEL:
                    logger.info("Gemini primary model unavailable; answered with fallback model %s", model_name)
                return answer.strip(), citations
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            is_quota = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
            logger.warning(
                "Gemini model %s failed (%s); %s",
                model_name,
                "quota exhausted" if is_quota else type(exc).__name__,
                "trying next model" if model_name != models_to_try[-1] else "no models left",
            )
            continue

    if last_error is not None:
        logger.error(
            "All Gemini models failed, falling back to template answers. Last error: %s", last_error
        )
    return _compose_from_retrieval(query, result)


# ---------------------------------------------------------------------------
# Provider: Anthropic Claude (existing integration, preserved)
# ---------------------------------------------------------------------------

def _compose_via_anthropic(query: str, result: RetrievalResult) -> tuple[str, list[Citation]]:
    settings = get_settings()
    try:
        import anthropic  # type: ignore
    except ImportError as exc:
        raise NotImplementedError(
            "LLM_PROVIDER=anthropic requires the 'anthropic' package (pip install anthropic)."
        ) from exc

    grounding_text, citations = _compose_from_retrieval(query, result)
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    system_prompt = (
        "You are a medical-information assistant. Rewrite the following grounded facts into a "
        "clear, empathetic, well-organized answer to the user's question. Do NOT add any medical "
        "fact that is not present in the grounded facts below. Do not diagnose or recommend a "
        "specific course of action beyond what's stated."
    )
    message = client.messages.create(
        model="claude-3-5-sonnet-latest",
        max_tokens=600,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"User question: {query}\n\nGrounded facts:\n{grounding_text}",
            }
        ],
    )
    text = "".join(block.text for block in message.content if hasattr(block, "text"))
    return text, citations


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ask(
    db: Session,
    query: str,
    patient_condition_names: list[str] | None = None,
    patient_drug_ids: list[str] | None = None,
    history: list[dict] | None = None,
    patient_context: str | None = None,
    language: str | None = None,
) -> ChatAnswer:
    """
    Main entry point called by the chat router.

    Parameters
    ----------
    db                      : Active DB session (for retriever).
    query                   : The user's current message.
    patient_condition_names : Patient's known conditions (for RAG context).
    patient_drug_ids        : Patient's confirmed medication IDs (for RAG context).
    history                 : Prior conversation turns as Gemini-format dicts
                              [{"role": "user"|"model", "parts": [{"text": "..."}]}].
                              Only used by the Google provider.
    patient_context         : Rendered text of this patient's own data file
                              (profile, allergies, conditions, confirmed
                              medicines, reminder times) so questions like
                              "what am I taking?" answer from real records.
    """
    # 1. Emergency check — always first, no LLM involved
    result = retrieve(db, query, patient_condition_names, patient_drug_ids)
    if result.is_emergency:
        return ChatAnswer(answer=EMERGENCY_RESPONSE, citations=[], is_emergency_escalation=True)

    result.patient_context = patient_context or ""

    # 2. Choose composer based on configured provider. Any provider failure
    #    (missing package, bad key, network/quota error) degrades to the
    #    deterministic retrieval composer rather than a 500 -- a chatbot
    #    answer that's less fluent beats one that errors out entirely.
    settings = get_settings()

    try:
        if settings.LLM_PROVIDER == "google" and settings.GOOGLE_API_KEY:
            answer_text, citations = _compose_via_google(
                query, result, history=history, language=language
            )
        elif settings.LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY:
            answer_text, citations = _compose_via_anthropic(query, result)
        else:
            answer_text, citations = _compose_from_retrieval(query, result)
    except Exception:  # noqa: BLE001
        logger.exception("LLM_PROVIDER=%s failed, falling back to retrieval composer", settings.LLM_PROVIDER)
        answer_text, citations = _compose_from_retrieval(query, result)

    return ChatAnswer(answer=answer_text, citations=citations, is_emergency_escalation=False)
