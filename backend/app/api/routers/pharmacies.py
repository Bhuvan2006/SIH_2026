from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_patient
from app.db.database import get_db
from app.models.models import Patient
from app.schemas.schemas import PharmacyOut
from app.services.places_service import get_places_provider

router = APIRouter(prefix="/pharmacies", tags=["pharmacy-locator"])

LOCATOR_DISCLAIMER = (
    "These are nearby pharmacies, not a confirmation that any specific medicine is in stock. "
    "Call ahead or check the pharmacy's own app before making a trip."
)


@router.get("/nearby", response_model=list[PharmacyOut])
def nearby_pharmacies(
    lat: float = Query(..., description="Patient latitude"),
    lon: float = Query(..., description="Patient longitude"),
    radius_km: float = Query(5.0, ge=0.1, le=50.0),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    patient: Patient = Depends(get_current_patient),
):
    provider = get_places_provider()
    results = provider.nearby_pharmacies(db, lat, lon, radius_km, limit)
    return [PharmacyOut(**r) for r in results]
