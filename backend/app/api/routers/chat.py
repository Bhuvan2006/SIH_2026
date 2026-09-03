import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_current_patient
from app.db.database import get_db
from app.models.models import ChatMessage, ChatSession, Condition, Medication, Patient
from app.schemas.schemas import ChatAskRequest, ChatAskResponse, ChatCitation
from app.services.chatbot_service import DISCLAIMER, ask
from app.services.patient_file_service import (
    read_patient_file,
    render_patient_context,
    write_patient_file,
)

router = APIRouter(prefix="/chat", tags=["chatbot"])


def _load_history(db: Session, session_id: str, max_turns: int) -> list[dict]:
    """
    Returns the last `max_turns` user+assistant message pairs from the given
    session formatted as Gemini content dicts:
      {"role": "user"|"model", "parts": [{"text": "..."}]}

    Notes:
    - We map DB role "assistant" → Gemini role "model".
    - We fetch 2×max_turns rows (each turn = 1 user + 1 assistant message).
    - Only text content is included; citation JSON stored in DB is not re-sent.
    """
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(max_turns * 2)
        .all()
    )
    # Reverse so chronological order is oldest → newest
    messages = list(reversed(messages))

    history = []
    for msg in messages:
        role = "model" if msg.role == "assistant" else "user"
        history.append({"role": role, "parts": [{"text": msg.content}]})
    return history


@router.post("/ask", response_model=ChatAskResponse)
def ask_chatbot(
    payload: ChatAskRequest,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    settings = get_settings()

    # ── Session management ─────────────────────────────────────────────────
    if payload.session_id:
        session = (
            db.query(ChatSession)
            .filter(
                ChatSession.id == payload.session_id,
                ChatSession.patient_id == patient.id,
            )
            .first()
        )
    else:
        session = None

    if not session:
        session = ChatSession(patient_id=patient.id)
        db.add(session)
        db.flush()

    # ── Persist user message ───────────────────────────────────────────────
    db.add(ChatMessage(session_id=session.id, role="user", content=payload.message))
    db.flush()

    # ── Patient context (conditions + confirmed medications) ───────────────
    condition_names = [
        c.name
        for c in db.query(Condition).filter(Condition.patient_id == patient.id).all()
    ]
    drug_ids = [
        m.matched_drug_id
        for m in db.query(Medication)
        .filter(
            Medication.patient_id == patient.id,
            Medication.is_confirmed == True,  # noqa: E712
        )
        .all()
        if m.matched_drug_id
    ]

    # ── Conversation history for multi-turn LLM context ───────────────────
    history = _load_history(db, session.id, max_turns=settings.CHAT_HISTORY_TURNS)

    # ── This patient's own data file (profile, allergies, medicines) ───────
    # Rebuilt lazily if it doesn't exist yet, so patients created before the
    # file store was introduced still get personalised answers.
    record = read_patient_file(patient.id)
    if record is None:
        write_patient_file(db, patient.id)
        record = read_patient_file(patient.id)
    patient_context = render_patient_context(record) if record else ""

    # ── Ask the chatbot service ────────────────────────────────────────────
    result = ask(
        db,
        payload.message,
        patient_condition_names=condition_names,
        patient_drug_ids=drug_ids,
        history=history,
        patient_context=patient_context,
        language=payload.language or patient.preferred_language,
    )

    # ── Persist assistant response ─────────────────────────────────────────
    db.add(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content=result.answer,
            citations=json.dumps([c.source_id for c in result.citations]),
            is_emergency_escalation=result.is_emergency_escalation,
        )
    )
    db.commit()

    return ChatAskResponse(
        session_id=session.id,
        answer=result.answer,
        citations=[
            ChatCitation(source_id=c.source_id, label=c.label) for c in result.citations
        ],
        is_emergency_escalation=result.is_emergency_escalation,
        disclaimer=DISCLAIMER,
    )


@router.get("/sessions/{session_id}/messages")
def get_session_messages(
    session_id: str,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.patient_id == patient.id)
        .first()
    )
    if not session:
        return []
    return [
        {
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at,
            "is_emergency_escalation": m.is_emergency_escalation,
        }
        for m in session.messages
    ]
