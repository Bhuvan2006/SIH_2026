"""
Per-medicine safety screening for a freshly-scanned prescription.

Runs each extracted medicine against:
  1. Banned / withdrawn / dose-restricted lists (CDSCO + global withdrawals)
  2. The patient's recorded allergies -- including drug-CLASS matches, so a
     recorded "penicillin" allergy flags Amoxicillin and Augmentin, not just
     the literal word "penicillin"
  3. The drug's own contraindications vs. the patient's recorded conditions
  4. Duplicate therapy within the same prescription (two drugs of one class)
  5. Known interactions between medicines on the same prescription

IMPORTANT -- what this is and is not
------------------------------------
This is a prompt to ASK, never a verdict. Per the build plan's first
guardrail, Arogya suggests and never prescribes: nothing here blocks a
medicine, changes a dose, or tells a patient to stop taking something. Every
flag resolves to "confirm this with your doctor or pharmacist". The checks are
deliberately conservative -- a false alarm costs a question, a missed
penicillin allergy can kill someone.

The knowledge base is a small curated sample, so absence of a flag is NOT
evidence of safety. The UI must say so.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.models import Allergy, Condition, DrugKnowledge, Medication, Patient

logger = logging.getLogger("arogya.safety")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


@dataclass
class SafetyFlag:
    kind: str          # banned | allergy | contraindication | duplicate | interaction
    severity: str      # critical | warning | info
    title: str
    detail: str
    action: str        # what the patient should actually do
    source: str | None = None


@dataclass
class MedicationSafety:
    raw_name: str
    matched_drug_id: str | None
    flags: list[SafetyFlag] = field(default_factory=list)

    @property
    def worst_severity(self) -> str | None:
        for level in (SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO):
            if any(f.severity == level for f in self.flags):
                return level
        return None


# --- Allergy cross-referencing ---------------------------------------------
# A patient writes the allergy the way they were told it ("penicillin",
# "sulpha"), which rarely equals the prescribed molecule. These map an allergy
# term to substrings that may appear in a drug's generic name, composition, or
# class, so class-level cross-reactivity is caught.
ALLERGY_CLASS_MAP: dict[str, list[str]] = {
    "penicillin": ["penicillin", "amoxicillin", "ampicillin", "cloxacillin", "piperacillin"],
    "cephalosporin": ["cephalosporin", "cefixime", "cefuroxime", "ceftriaxone", "cephalexin"],
    "sulpha": ["sulfa", "sulpha", "sulfamethoxazole", "cotrimoxazole", "sulfasalazine"],
    "sulfa": ["sulfa", "sulpha", "sulfamethoxazole", "cotrimoxazole", "sulfasalazine"],
    "nsaid": ["nsaid", "ibuprofen", "diclofenac", "naproxen", "aspirin", "acetylsalicylic", "etodolac"],
    "aspirin": ["aspirin", "acetylsalicylic", "nsaid"],
    "quinolone": ["quinolone", "ciprofloxacin", "levofloxacin", "ofloxacin", "norfloxacin"],
    "macrolide": ["macrolide", "azithromycin", "erythromycin", "clarithromycin"],
    "tetracycline": ["tetracycline", "doxycycline", "minocycline"],
    "statin": ["statin", "atorvastatin", "rosuvastatin", "simvastatin"],
    "iodine": ["iodine", "iodinated", "contrast"],
    "egg": ["egg", "influenza vaccine"],
}

# --- Condition <-> contraindication matching -------------------------------
# Patient conditions are stored as slugs (diabetes_type_2, ckd...). A drug's
# contraindications are free text off the label. These map one to the other.
CONDITION_KEYWORDS: dict[str, list[str]] = {
    "ckd": ["kidney", "renal", "nephro"],
    "kidney_disease": ["kidney", "renal", "nephro"],
    "liver_disease": ["liver", "hepatic", "hepato"],
    "asthma": ["asthma", "bronchospasm", "respiratory"],
    "hypertension": ["hypertension", "blood pressure"],
    "diabetes_type_1": ["diabet", "hypoglyc"],
    "diabetes_type_2": ["diabet", "hypoglyc"],
    "heart_failure": ["heart failure", "cardiac failure", "decompensated"],
    "peptic_ulcer": ["peptic ulcer", "gastric ulcer", "gi bleed"],
    "pregnancy": ["pregnan", "trimester"],
    "breastfeeding": ["breastfeed", "lactat"],
    "epilepsy": ["seizure", "epilep"],
    "glaucoma": ["glaucoma"],
    "thyroid": ["thyroid"],
    "hypothyroidism": ["thyroid"],
}

CONDITION_LABELS: dict[str, str] = {
    "ckd": "chronic kidney disease",
    "kidney_disease": "kidney disease",
    "liver_disease": "liver disease",
    "diabetes_type_1": "type 1 diabetes",
    "diabetes_type_2": "type 2 diabetes",
    "heart_failure": "heart failure",
    "peptic_ulcer": "peptic ulcer",
    "hypothyroidism": "hypothyroidism",
}


def _load_banned() -> list[dict]:
    try:
        raw = json.loads((DATA_DIR / "banned_drugs.json").read_text(encoding="utf-8"))
        return raw.get("entries", [])
    except Exception:  # noqa: BLE001
        logger.exception("Could not load banned_drugs.json; banned-drug screening disabled")
        return []


_BANNED = _load_banned()


def _load_cdsco() -> list[dict]:
    """
    The full CDSCO section 26A prohibition list, OCR'd from the official PDF
    (scripts/parse_cdsco_banned_pdf.py). Only entries whose molecules parsed
    cleanly are usable as match rules -- see _CDSCO_MATCHABLE.
    """
    try:
        raw = json.loads((DATA_DIR / "banned_drugs_cdsco.json").read_text(encoding="utf-8"))
        return raw.get("entries", [])
    except Exception:  # noqa: BLE001
        logger.exception("Could not load banned_drugs_cdsco.json; CDSCO screening disabled")
        return []


_CDSCO_ALL = _load_cdsco()

# Class rules ("corticosteroids with any other drug for internal use") are kept
# in the file for reference but not matched: deciding whether a medicine is a
# corticosteroid needs drug-class data we hold for the 45 curated drugs only,
# and applying the rule on a name match would flag half the catalogue.
_CDSCO_MATCHABLE = [
    entry
    for entry in _CDSCO_ALL
    if entry.get("kind") in ("single", "combination") and entry.get("ingredients")
]

# The scan cannot reliably attribute the source document's footnote markers to
# individual rows, and some of those footnotes mark prohibitions that are
# stayed, revoked, or under Supreme Court appeal. So every CDSCO flag says the
# legal status may have moved rather than asserting a live ban -- the patient's
# doctor is the one who can check.
CDSCO_STATUS_CAVEAT = (
    "Some entries on this list are stayed or under appeal, so the current legal status "
    "can differ."
)


def _class_key(drug_class: str) -> str:
    """
    Normalises a drug-class label so equivalent classes compare equal.

    Class strings in the knowledge base are prose ("NSAID (Nonsteroidal
    anti-inflammatory)", "Proton pump inhibitor"), so this strips any
    parenthetical, lowercases, and collapses whitespace.
    """
    base = re.sub(r"\(.*?\)", "", drug_class or "")
    return re.sub(r"\s+", " ", base).strip().lower()


def _haystack(raw_name: str, drug: DrugKnowledge | None, composition: str | None = None) -> str:
    """All the text we're willing to match a rule against, lowercased.

    `composition` is the catalogue's full ingredient list for the scanned
    product. It matters most for banned fixed-dose combinations: the brand name
    alone ("Zerodol PT") says nothing about the three molecules inside it.
    """
    parts = [raw_name or "", composition or ""]
    if drug:
        parts += [drug.generic_name or "", drug.composition or "", drug.drug_class or ""]
        try:
            parts += json.loads(drug.brand_names or "[]")
        except json.JSONDecodeError:
            pass
    return " ".join(parts).lower()


def _check_banned(
    raw_name: str, drug: DrugKnowledge | None, composition: str | None = None
) -> list[SafetyFlag]:
    hay = _haystack(raw_name, drug, composition)
    flags: list[SafetyFlag] = []
    for entry in _BANNED:
        term = entry["match"].lower()
        # Combination rules ("naproxen + esomeprazole") need every component
        # present; single-molecule rules just need the word.
        parts = [p.strip() for p in term.split("+")]
        if all(re.search(rf"\b{re.escape(p)}", hay) for p in parts if p):
            status = entry.get("status", "restricted")
            flags.append(
                SafetyFlag(
                    kind="banned",
                    severity=SEVERITY_CRITICAL if status in ("banned", "withdrawn") else SEVERITY_WARNING,
                    title=(
                        f"This medicine appears to be {status} in India"
                        if status != "restricted"
                        else "This medicine is restricted in India"
                    ),
                    detail=f"{entry.get('scope', '')} {entry.get('reason', '')}".strip(),
                    action=(
                        "Do not start this without speaking to your doctor — show them this note "
                        "and ask whether the prescription is still correct."
                    ),
                    source=entry.get("authority"),
                )
            )

    # The curated list already covers a few single molecules in more clinical
    # detail (why it is restricted, at what dose). When it has spoken, a second
    # generic "this molecule is on the list" banner adds noise, not information
    # -- so single-molecule CDSCO entries defer. Combination entries never do:
    # they are the fact nothing else in the app knows.
    already_flagged_single = any(f.severity == SEVERITY_CRITICAL for f in flags)
    flags += _check_cdsco(hay, skip_single=already_flagged_single)
    return flags


def _check_cdsco(hay: str, skip_single: bool = False) -> list[SafetyFlag]:
    """
    Matches the CDSCO section 26A prohibition list.

    A combination entry only fires when EVERY one of its molecules is present:
    "Nimesulide + Paracetamol" is prohibited as a combination, while nimesulide
    alone is merely dose-restricted (already covered by the curated list). A
    partial match would tell a patient their paracetamol is banned.
    """
    flags: list[SafetyFlag] = []
    seen: set[str] = set()

    for entry in _CDSCO_MATCHABLE:
        ingredients = [i for i in entry.get("ingredients", []) if i]
        if not ingredients:
            continue
        if not all(re.search(rf"\b{re.escape(i)}", hay) for i in ingredients):
            continue

        key = "+".join(sorted(ingredients))
        if key in seen:
            continue
        seen.add(key)

        combination = len(ingredients) > 1
        if skip_single and not combination:
            continue
        flags.append(
            SafetyFlag(
                kind="banned",
                severity=SEVERITY_CRITICAL,
                title=(
                    "This combination is on India's prohibited-drugs list"
                    if combination
                    else "This medicine is on India's prohibited-drugs list"
                ),
                detail=(
                    f"{entry.get('text', '').strip()} — prohibited for manufacture and sale "
                    f"under section 26A of the Drugs & Cosmetics Act 1940. "
                    f"{CDSCO_STATUS_CAVEAT}"
                ),
                action=(
                    "Do not start this without speaking to your doctor. Show them this note "
                    "and ask whether the prescription should be changed."
                ),
                source="CDSCO section 26A list, Ministry of Health and Family Welfare",
            )
        )

    return flags


# ---------------------------------------------------------------------------
# Menopause and oestrogen-lowering therapy
# ---------------------------------------------------------------------------
#
# Aromatase inhibitors shut down the small amount of oestrogen a
# postmenopausal woman still makes, and the side effects land squarely on top
# of the symptoms she already has: hot flushes, joint and bone pain, bone
# density loss.
#
# The flag is a WARNING, never critical, and it never says "avoid". These are
# often essential cancer treatment where stopping is far more dangerous than
# the side effects; the right response is supportive care and a conversation,
# not a scare. Getting that tone wrong could lead someone to quit a breast
# cancer therapy on their own.
AROMATASE_INHIBITORS = {
    "anastrozole": "Anastrozole",
    "letrozole": "Letrozole",
    "exemestane": "Exemestane",
}

# What the patient may have recorded, including the free-text "other
# condition" entries the profile allows.
MENOPAUSE_TERMS = (
    "menopause",
    "menopausal",
    "perimenopause",
    "postmenopause",
    "post-menopause",
    "post menopausal",
    "hot flush",
    "hot flash",
    "osteoporosis",
    "osteopenia",
)


def _check_menopause(db: Session, patient_id: str, raw_name: str, composition: str | None) -> list[SafetyFlag]:
    hay = f"{raw_name or ''} {composition or ''}".lower()
    present = [label for key, label in AROMATASE_INHIBITORS.items() if re.search(rf"\b{key}", hay)]
    if not present:
        return []

    recorded = [
        (c.name or "").strip().lower()
        for c in db.query(Condition).filter(Condition.patient_id == patient_id).all()
    ]
    matched = next(
        (r for r in recorded if any(term in r for term in MENOPAUSE_TERMS)),
        None,
    )
    if not matched:
        return []

    drug_label = " and ".join(present)
    return [
        SafetyFlag(
            kind="menopause",
            severity=SEVERITY_WARNING,
            title=f"{drug_label} can make menopausal symptoms worse",
            detail=(
                f"{drug_label} works by lowering oestrogen to very low levels. Because you have "
                f"“{matched}” on your record, the usual side effects — hot flushes, joint "
                "pain and stiffness, and loss of bone density — may hit harder and affect your "
                "day-to-day life more than they would otherwise. This is expected, not a sign "
                "something has gone wrong."
            ),
            action=(
                "Do NOT stop this medicine on your own — where it is prescribed for breast "
                "cancer it is doing important work, and stopping carries a far bigger risk than "
                "the side effects. Instead, tell your doctor how bad the symptoms are: there is "
                "supportive treatment for flushes and joint pain, and bone density can be "
                "monitored and protected."
            ),
            source="Standard oncology prescribing guidance for aromatase inhibitors",
        )
    ]


def _check_allergies(
    db: Session, patient_id: str, raw_name: str, drug: DrugKnowledge | None
) -> list[SafetyFlag]:
    hay = _haystack(raw_name, drug)
    flags: list[SafetyFlag] = []

    for allergy in db.query(Allergy).filter(Allergy.patient_id == patient_id).all():
        allergen = (allergy.allergen or "").strip().lower()
        if not allergen:
            continue

        terms = {allergen}
        for key, expansions in ALLERGY_CLASS_MAP.items():
            if key in allergen or allergen in key:
                terms.update(expansions)

        # Both word boundaries matter. With a leading \b only, the term
        # "sulpha" matched inside "Ferrous Sulphate" and told a pregnant
        # patient her antenatal iron clashed with her sulfa-drug allergy. A
        # sulphate salt has nothing to do with sulfonamides, and a false
        # allergy warning on an essential supplement is the kind that gets a
        # medicine stopped. The optional plural keeps "penicillin" matching
        # "penicillins"; longer sulfonamides are covered by their own entries
        # in ALLERGY_CLASS_MAP rather than by prefix.
        hit = next(
            (t for t in terms if t and re.search(rf"\b{re.escape(t)}(?:s|es)?\b", hay)),
            None,
        )
        if not hit:
            continue

        severe = (allergy.severity or "").lower() in ("severe", "anaphylaxis")
        reaction = f" Recorded reaction: {allergy.reaction}." if allergy.reaction else ""
        flags.append(
            SafetyFlag(
                kind="allergy",
                severity=SEVERITY_CRITICAL,
                title=f"You have a recorded allergy to {allergy.allergen}",
                detail=(
                    f"This medicine matches that allergy"
                    + (f" (matched on '{hit}')" if hit != allergen else "")
                    + f".{reaction}"
                    + (
                        " Your record marks this allergy as severe/anaphylactic."
                        if severe
                        else ""
                    )
                ),
                action=(
                    "Do not take this until your doctor or pharmacist has confirmed it is safe. "
                    "Tell them about this allergy explicitly."
                ),
                source="Your Arogya profile",
            )
        )
    return flags


def _check_pregnancy(
    patient: "Patient | None", raw_name: str, drug: DrugKnowledge | None
) -> list[SafetyFlag]:
    """
    Hard red flag when a pregnant or breastfeeding patient is prescribed a
    medicine whose own label contraindicates it.

    Deliberately CRITICAL rather than a caution. Elsewhere this service errs
    toward "ask your doctor"; here the asymmetry is different — a medicine
    like warfarin, isotretinoin or an ACE inhibitor taken in pregnancy can
    cause irreversible harm to a fetus in a single course, and the window to
    catch it is now, while the patient is reviewing the scan.

    It still never blocks anything: the doctor may have weighed the risk
    deliberately. It makes sure the patient KNOWS to ask.
    """
    if not patient or not drug:
        return []
    pregnant = bool(getattr(patient, "is_pregnant", False))
    breastfeeding = bool(getattr(patient, "is_breastfeeding", False))
    if not (pregnant or breastfeeding):
        return []

    try:
        contraindications = json.loads(drug.contraindications or "[]")
    except json.JSONDecodeError:
        return []

    pattern = r"pregnan|trimester|foetal|fetal" if pregnant else r""
    if breastfeeding:
        pattern = (pattern + "|" if pattern else "") + r"breastfeed|lactat|nursing"

    hits = [c for c in contraindications if c and re.search(pattern, c.lower())]
    if not hits:
        return []

    state = "pregnant" if pregnant else "breastfeeding"
    if pregnant and breastfeeding:
        state = "pregnant"

    return [
        SafetyFlag(
            kind="pregnancy",
            severity=SEVERITY_CRITICAL,
            title=f"Not normally used in pregnancy — and your profile says you are {state}",
            detail=(
                f"{drug.generic_name} lists this as a reason not to take it: “{hits[0]}”. "
                f"Medicines in this group can affect a developing baby, and the risk can differ "
                f"by trimester."
            ),
            action=(
                "Do not take the first dose until you have confirmed with your doctor that they "
                "prescribed this knowing you are " + state + ". Ask specifically about this medicine."
            ),
            source=drug.source_citation,
        )
    ]


def _check_conditions(
    db: Session, patient_id: str, drug: DrugKnowledge | None
) -> list[SafetyFlag]:
    if not drug or not drug.contraindications:
        return []

    try:
        contraindications = json.loads(drug.contraindications or "[]")
    except json.JSONDecodeError:
        return []

    conditions = db.query(Condition).filter(Condition.patient_id == patient_id).all()
    flags: list[SafetyFlag] = []

    for condition in conditions:
        slug = (condition.name or "").lower()
        keywords = CONDITION_KEYWORDS.get(slug, [slug.replace("_", " ")])
        for text in contraindications:
            low = (text or "").lower()
            if any(kw and kw in low for kw in keywords):
                label = CONDITION_LABELS.get(slug, slug.replace("_", " "))
                flags.append(
                    SafetyFlag(
                        kind="contraindication",
                        severity=SEVERITY_WARNING,
                        # Named plainly. "Caution with your kidney disease" reads
                        # as a footnote; a patient skimming needs to register
                        # that this medicine may not be one they can take.
                        title=f"You may not be able to take this — you have {label}",
                        detail=(
                            f"{drug.generic_name} is normally not given to people with {label}. "
                            f"The medicine's own label lists this as a reason not to use it: “{text}”. "
                            f"Your doctor may still have chosen it deliberately for your situation, "
                            f"but they need to confirm that."
                        ),
                        action=(
                            f"Do not start this until you have asked your doctor whether it is safe "
                            f"with your {label}."
                        ),
                        source=drug.source_citation,
                    )
                )
                break
    return flags


def _check_duplicate_and_interactions(
    prescribed: list[tuple[str, DrugKnowledge | None]],
    index: int,
) -> list[SafetyFlag]:
    raw_name, drug = prescribed[index]
    if not drug:
        return []

    flags: list[SafetyFlag] = []
    others = [(n, d) for i, (n, d) in enumerate(prescribed) if i != index and d]

    # Same therapeutic class prescribed twice. Compared on a normalised class
    # token, not the raw string: "NSAID" and "NSAID (Nonsteroidal
    # anti-inflammatory)" are the same class and an equality check misses it.
    if drug.drug_class:
        mine = _class_key(drug.drug_class)
        for other_name, other in others:
            if other.drug_class and _class_key(other.drug_class) == mine:
                if other.id == drug.id:
                    continue
                flags.append(
                    SafetyFlag(
                        kind="duplicate",
                        severity=SEVERITY_WARNING,
                        title="Two medicines of the same type",
                        detail=(
                            f"{drug.generic_name} and {other.generic_name} are both "
                            f"{drug.drug_class.lower()}. Taking both can double the effect and the "
                            f"side effects."
                        ),
                        action="Check with your doctor that both are meant to be taken together.",
                        source=drug.source_citation,
                    )
                )
                break

    # This drug's own interaction list naming another prescribed medicine.
    try:
        interactions = json.loads(drug.common_interactions or "[]")
    except json.JSONDecodeError:
        interactions = []

    for text in interactions:
        low = (text or "").lower()
        for other_name, other in others:
            names = [other.generic_name] + json.loads(other.brand_names or "[]")
            hit = next(
                (n for n in names if n and len(n) >= 4 and re.search(rf"\b{re.escape(n.lower())}", low)),
                None,
            )
            if hit:
                flags.append(
                    SafetyFlag(
                        kind="interaction",
                        severity=SEVERITY_WARNING,
                        title=f"May interact with {other.generic_name}",
                        detail=f"Both are on this prescription. Noted interaction: “{text}”.",
                        action="Ask your doctor or pharmacist whether these are safe together.",
                        source=drug.source_citation,
                    )
                )
                break
    return flags


def screen_raw_text_for_banned(
    raw_text: str, already_flagged: list[MedicationSafety]
) -> list[SafetyFlag]:
    """
    Scans the raw OCR transcription for banned/restricted molecules.

    This is the safety net for a real gap: structured extraction only keeps
    medicines that fuzzy-match the curated knowledge base, so a drug we don't
    stock -- which includes several banned ones, precisely because they are no
    longer legitimately prescribed -- is dropped from `extracted` entirely and
    would never reach the per-medicine screening. Nimesulide was exactly this
    case in testing. Matching the transcription directly means a banned drug
    still gets surfaced even when we know nothing else about it.

    Flags already raised against a matched medicine are skipped so the patient
    doesn't see the same warning twice.
    """
    if not raw_text:
        return []

    seen_titles = {f.title for ms in already_flagged for f in ms.flags}
    hay = raw_text.lower()
    flags: list[SafetyFlag] = []
    emitted: set[str] = set()

    for entry in _BANNED:
        term = entry["match"].lower()
        parts = [p.strip() for p in term.split("+")]
        if not all(re.search(rf"\b{re.escape(p)}", hay) for p in parts if p):
            continue

        status = entry.get("status", "restricted")
        label = entry["match"].title()
        if label in emitted:
            continue
        emitted.add(label)

        title = (
            f"“{label}” appears on this prescription and is {status} in India"
            if status != "restricted"
            else f"“{label}” appears on this prescription and is restricted in India"
        )
        if title in seen_titles:
            continue

        flags.append(
            SafetyFlag(
                kind="banned",
                severity=SEVERITY_CRITICAL if status in ("banned", "withdrawn") else SEVERITY_WARNING,
                title=title,
                detail=(
                    f"{entry.get('scope', '')} {entry.get('reason', '')}".strip()
                    + " We read this from the prescription text, so double-check we read the name correctly."
                ),
                action=(
                    "Please confirm this medicine with your doctor before taking it — show them "
                    "this note and ask whether it is still the right prescription."
                ),
                source=entry.get("authority"),
            )
        )
    return flags


def screen_prescription(
    db: Session,
    patient_id: str,
    medications: list[tuple[str, str | None]],
    compositions: list[str | None] | None = None,
) -> list[MedicationSafety]:
    """
    Screens every extracted medicine for one patient.

    `medications` is [(raw_name, matched_drug_id | None), ...] straight from
    the OCR/vision extraction, so this runs BEFORE anything is confirmed --
    which is the point: the patient sees the concerns while reviewing, not
    after reminders are already scheduled.

    `compositions`, when supplied, is the catalogue's full ingredient list per
    medicine, positionally aligned with `medications`. Without it a banned
    fixed-dose combination is invisible: "Zerodol PT" is just a brand name, and
    the prohibition is on the three molecules inside it.
    """
    compositions = compositions or [None] * len(medications)
    resolved: list[tuple[str, DrugKnowledge | None]] = []
    for raw_name, drug_id in medications:
        drug = (
            db.query(DrugKnowledge).filter(DrugKnowledge.id == drug_id).first() if drug_id else None
        )
        resolved.append((raw_name, drug))

    # Medicines the patient is already confirmed to be taking, so we can warn
    # about a new prescription clashing with an existing allergy-free but
    # duplicated therapy.
    existing = (
        db.query(Medication)
        .filter(Medication.patient_id == patient_id, Medication.is_confirmed == True)  # noqa: E712
        .all()
    )

    patient = db.query(Patient).filter(Patient.id == patient_id).first()

    results: list[MedicationSafety] = []
    for i, (raw_name, drug) in enumerate(resolved):
        flags: list[SafetyFlag] = []
        flags += _check_banned(raw_name, drug, compositions[i] if i < len(compositions) else None)
        flags += _check_allergies(db, patient_id, raw_name, drug)
        # Pregnancy before the general condition check: if both fire, the
        # pregnancy wording is the one that must lead.
        flags += _check_pregnancy(patient, raw_name, drug)
        flags += _check_conditions(db, patient_id, drug)
        flags += _check_menopause(
            db, patient_id, raw_name, compositions[i] if i < len(compositions) else None
        )
        flags += _check_duplicate_and_interactions(resolved, i)

        # Already-taking check: same canonical drug already active.
        if drug:
            for med in existing:
                if med.matched_drug_id == drug.id:
                    flags.append(
                        SafetyFlag(
                            kind="duplicate",
                            severity=SEVERITY_INFO,
                            title="You are already taking this",
                            detail=(
                                f"{drug.generic_name} is already in your current medicines. This may "
                                f"be a repeat prescription, or it may be an accidental double-up."
                            ),
                            action="Confirm with your doctor whether this replaces the existing one.",
                            source="Your Arogya record",
                        )
                    )
                    break

        results.append(
            MedicationSafety(raw_name=raw_name, matched_drug_id=drug.id if drug else None, flags=flags)
        )

    return results
