from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, generate_otp, verify_otp
from app.db.database import get_db
from app.models.models import Patient, Doctor
from app.schemas.schemas import OTPRequest, OTPRequestResponse, OTPVerify, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post("/otp/request", response_model=OTPRequestResponse)
def request_otp(payload: OTPRequest):
    """
    Mock OTP send. In production this calls an SMS/WhatsApp provider
    (Twilio, MSG91) via NotifierProvider. In dev mode the OTP is returned
    directly in the response (and "000000" always works) so the whole
    login flow is testable without real SMS.
    """
    code = generate_otp(payload.phone)
    if settings.OTP_DEV_MODE:
        return OTPRequestResponse(
            message="Dev mode: OTP generated (also accepting 000000).",
            dev_otp=code,
        )
    # Production path would call the SMS provider here and NOT return the code.
    return OTPRequestResponse(message="OTP sent.")


@router.post("/otp/verify", response_model=TokenResponse)
def verify_otp_and_login(payload: OTPVerify, db: Session = Depends(get_db)):
    from fastapi import HTTPException, status

    if not verify_otp(payload.phone, payload.otp):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OTP")

    patient = db.query(Patient).filter(Patient.phone == payload.phone).first()
    is_new = False
    if not patient:
        patient = Patient(phone=payload.phone)
        db.add(patient)
        db.commit()
        db.refresh(patient)
        is_new = True

    token = create_access_token(patient.id, role="patient")
    return TokenResponse(access_token=token, patient_id=patient.id, is_new_patient=is_new, role="patient")


@router.post("/doctor/otp/request", response_model=OTPRequestResponse)
def doctor_request_otp(payload: OTPRequest):
    code = generate_otp(payload.phone)
    if settings.OTP_DEV_MODE:
        return OTPRequestResponse(
            message="Dev mode: OTP generated (also accepting 000000).",
            dev_otp=code,
        )
    return OTPRequestResponse(message="OTP sent.")


@router.post("/doctor/otp/verify", response_model=TokenResponse)
def doctor_verify_otp_and_login(payload: OTPVerify, db: Session = Depends(get_db)):
    from fastapi import HTTPException, status

    if not verify_otp(payload.phone, payload.otp):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OTP")

    doctor = db.query(Doctor).filter(Doctor.phone == payload.phone).first()
    is_new = False
    if not doctor:
        doctor = Doctor(phone=payload.phone)
        db.add(doctor)
        db.commit()
        db.refresh(doctor)
        is_new = True

    token = create_access_token(doctor.id, role="doctor")
    return TokenResponse(access_token=token, doctor_id=doctor.id, is_new_doctor=is_new, role="doctor")
