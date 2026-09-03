"""
Retrieval layer for the chatbot's RAG pipeline.

Deliberately keyword/fuzzy-match based rather than embedding-based: this
keeps the prototype dependency-free (no vector DB, no embedding API key)
while still enforcing the core safety property from the build plan
(§6.6): the chatbot answers ONLY from retrieved, curated, citable
records -- never free-form generation of medical facts.

For a production system, swap this for real semantic search (pgvector +
an embedding model) over a licensed drug database; the interface
(`retrieve(query, patient_context) -> RetrievalResult`) stays the same so
`chatbot_service.py` doesn't need to change.
"""
import json
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.models import DrugKnowledge, Condition
from app.services.diet_service import all_diet_guidance

EMERGENCY_PATTERNS = [
    r"chest pain", r"can'?t breathe", r"cannot breathe", r"difficulty breathing",
    r"suicid", r"kill myself", r"want to die", r"overdose", r"overdosed",
    r"severe allergic", r"anaphyla", r"unconscious", r"unresponsive",
    r"seizure", r"stroke", r"heavy bleeding", r"coughing blood",
]

PREGNANCY_PATTERNS = [
    r"pregnan", r"expecting( a baby)?", r"trying to conceive", r"breastfeed", r"breast.feeding",
    r"nursing mother", r"lactat",
]


@dataclass
class DrugFact:
    drug_id: str
    generic_name: str
    composition: str
    storage_instructions: str | None
    common_interactions: list[str]
    contraindications: list[str]
    source_citation: str | None
    match_reason: str


@dataclass
class DietFact:
    condition_key: str
    label: str
    prefer: list[str]
    avoid: list[str]
    notes: str
    match_reason: str


@dataclass
class RetrievalResult:
    drug_facts: list[DrugFact] = field(default_factory=list)
    diet_facts: list[DietFact] = field(default_factory=list)
    is_emergency: bool = False
    is_pregnancy_query: bool = False
    # Rendered text of the patient's own data file (see patient_file_service).
    # Injected by the chat router so answers can reference the patient's real
    # medicines, allergies, and schedule rather than only generic drug facts.
    patient_context: str = ""


def detect_emergency(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(p, lowered) for p in EMERGENCY_PATTERNS)


def detect_pregnancy(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(p, lowered) for p in PREGNANCY_PATTERNS)


def _name_matches(name: str, query_lower: str) -> bool:
    """
    True if `name` (a drug's generic or brand name) is referenced in the
    query -- either as an exact substring, or via any single significant
    word from a multi-word name (e.g. "insulin" inside "how should I
    store my insulin" correctly matches the drug "Insulin Glargine"
    without requiring the full "insulin glargine" phrase).
    """
    name_lower = name.lower()
    if name_lower in query_lower:
        return True
    words = [w for w in re.split(r"\s+", name_lower) if len(w) >= 4]
    return any(re.search(rf"\b{re.escape(w)}\b", query_lower) for w in words)


def retrieve(
    db: Session,
    query: str,
    patient_condition_names: list[str] | None = None,
    patient_drug_ids: list[str] | None = None,
) -> RetrievalResult:
    result = RetrievalResult(is_emergency=detect_emergency(query))
    if result.is_emergency:
        return result

    query_lower = query.lower()
    result.is_pregnancy_query = detect_pregnancy(query_lower)
    patient_condition_names = patient_condition_names or []
    patient_drug_ids = patient_drug_ids or []

    # --- Drug facts: match on generic name, brand names, or drug class ---
    all_drugs = db.query(DrugKnowledge).all()
    seen_drug_ids: set[str] = set()

    query_names_a_specific_drug = any(
        _name_matches(name, query_lower)
        for drug in all_drugs
        for name in [drug.generic_name] + json.loads(drug.brand_names or "[]")
    )

    for drug in all_drugs:
        brand_names = json.loads(drug.brand_names or "[]")
        names_to_check = [drug.generic_name] + brand_names
        matched = False
        reason = ""

        for name in names_to_check:
            if _name_matches(name, query_lower):
                matched = True
                reason = f"matched drug name '{name}' in your question"
                break

        if not matched and drug.drug_class and drug.drug_class.lower().split(" ")[0] in query_lower:
            matched = True
            reason = f"matched drug class '{drug.drug_class}'"

        if not matched and drug.id in patient_drug_ids:
            # Patient is asking generally about "my medicines" (not a
            # specific drug by name) -- include their current meds as
            # context. Deliberately narrow trigger phrases: broader words
            # like "storage"/"interact" must NOT land here, or a question
            # about one drug (e.g. insulin) could get silently answered
            # with facts about an unrelated confirmed medication instead.
            if any(
                phrase in query_lower
                for phrase in [
                    "my medicine", "my medication", "my meds",
                    "current medication", "what i'm taking", "what am i taking",
                ]
            ):
                matched = True
                reason = "one of your current confirmed medications"

        if not matched and result.is_pregnancy_query and not query_names_a_specific_drug:
            # A general pregnancy-safety question ("what should I avoid
            # while pregnant?") that does NOT name a specific drug -- surface
            # any curated drug whose contraindications mention pregnancy or
            # breastfeeding. When the query DOES name a specific drug (e.g.
            # "is ibuprofen safe while pregnant?"), skip this broadening so
            # we don't pollute the answer/citations with unrelated drugs.
            contraindications = json.loads(drug.contraindications or "[]")
            if any(re.search(r"pregnan|breastfeed|lactat|trimester", c.lower()) for c in contraindications):
                matched = True
                reason = "flagged as a pregnancy/breastfeeding caution in the curated knowledge base"

        if matched and drug.id not in seen_drug_ids:
            seen_drug_ids.add(drug.id)
            result.drug_facts.append(
                DrugFact(
                    drug_id=drug.id,
                    generic_name=drug.generic_name,
                    composition=drug.composition,
                    storage_instructions=drug.storage_instructions,
                    common_interactions=json.loads(drug.common_interactions or "[]"),
                    contraindications=json.loads(drug.contraindications or "[]"),
                    source_citation=drug.source_citation,
                    match_reason=reason,
                )
            )

    # --- Diet facts: match on condition keywords in query, or patient's own conditions ---
    diet_data = all_diet_guidance()
    seen_conditions: set[str] = set()

    condition_keywords = {
        "diabetes_type_2": ["diabetes", "diabetic", "type 2", "blood sugar", "sugar"],
        "diabetes_type_1": ["type 1 diabetes"],
        "hypertension": ["hypertension", "blood pressure", "bp "],
        "dyslipidemia": ["cholesterol", "lipid"],
        "hypothyroidism": ["thyroid", "hypothyroid"],
        "ckd": ["kidney", "renal", "ckd"],
        "asthma": ["asthma", "inhaler", "wheeze"],
    }

    candidate_conditions = set(patient_condition_names)
    for key, keywords in condition_keywords.items():
        if any(kw in query_lower for kw in keywords):
            candidate_conditions.add(key)

    if any(w in query_lower for w in ["diet", "eat", "food", "avoid"]):
        # If they're asking a diet question generally, and we know their
        # conditions, surface those even without an explicit keyword match.
        candidate_conditions.update(patient_condition_names)

    for key in candidate_conditions:
        if key in diet_data and key not in seen_conditions:
            seen_conditions.add(key)
            entry = diet_data[key]
            result.diet_facts.append(
                DietFact(
                    condition_key=key,
                    label=entry["label"],
                    prefer=entry["prefer"],
                    avoid=entry["avoid"],
                    notes=entry["notes"],
                    match_reason="matched condition in your question or profile",
                )
            )

    return result
