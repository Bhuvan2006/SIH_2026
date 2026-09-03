import random
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import get_db
from app.models.models import Patient, Doctor

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)

# In-memory OTP store for the prototype. In production this belongs in
# Redis (with expiry) and OTP delivery goes through a real SMS provider
# (see NOTIFICATION_PROVIDER in config.py).
_otp_store: dict[str, str] = {}


def generate_otp(phone: str) -> str:
    code = f"{random.randint(0, 999999):06d}"
    _otp_store[phone] = code
    return code


def verify_otp(phone: str, otp: str) -> bool:
    if settings.OTP_DEV_MODE:
        # Dev convenience: the literal code "000000" always works so the
        # flow is testable without reading server logs/state.
        if otp == "000000":
            return True
    expected = _otp_store.get(phone)
    return expected is not None and expected == otp


def create_access_token(user_id: str, role: str = "patient") -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return {"sub": payload["sub"], "role": payload.get("role", "patient")}
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def get_current_patient(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Patient:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_access_token(credentials.credentials)
    if payload.get("role") != "patient":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized as patient")
    patient = db.query(Patient).filter(Patient.id == payload["sub"]).first()
    if not patient:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Patient not found")
    return patient

def get_current_doctor(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Doctor:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_access_token(credentials.credentials)
    if payload.get("role") != "doctor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized as doctor")
    doctor = db.query(Doctor).filter(Doctor.id == payload["sub"]).first()
    if not doctor:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Doctor not found")
    return doctor
