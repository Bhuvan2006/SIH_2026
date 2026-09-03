"""
Pharmacy locator service.

Mock provider (default): returns pharmacies from the bundled sample
dataset (app/data/pharmacies.json, seeded into the DB), sorted by
straight-line (haversine) distance from the patient's supplied
coordinates. This is explicitly "nearby pharmacies from a sample list,"
not a claim of real-time stock or a live directory -- see build plan
§6.9 on why promising confirmed availability would be an overclaim
without a real inventory integration.

Swap PLACES_PROVIDER to "google_places" in production and implement
GooglePlacesProvider using the Places Nearby Search API with
GOOGLE_PLACES_API_KEY.
"""
import math

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import Pharmacy


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class PlacesProvider:
    def nearby_pharmacies(self, db: Session, lat: float, lon: float, radius_km: float, limit: int) -> list[dict]:
        raise NotImplementedError


class MockPlacesProvider(PlacesProvider):
    def nearby_pharmacies(self, db: Session, lat: float, lon: float, radius_km: float, limit: int) -> list[dict]:
        results = []
        for pharmacy in db.query(Pharmacy).all():
            dist = haversine_km(lat, lon, pharmacy.latitude, pharmacy.longitude)
            if dist <= radius_km:
                results.append(
                    {
                        "id": pharmacy.id,
                        "name": pharmacy.name,
                        "address": pharmacy.address,
                        "latitude": pharmacy.latitude,
                        "longitude": pharmacy.longitude,
                        "phone": pharmacy.phone,
                        "distance_km": round(dist, 2),
                    }
                )
        results.sort(key=lambda r: r["distance_km"])
        return results[:limit]


class GooglePlacesProvider(PlacesProvider):
    def nearby_pharmacies(self, db: Session, lat: float, lon: float, radius_km: float, limit: int) -> list[dict]:
        raise NotImplementedError(
            "Google Places integration not wired up in this prototype. "
            "Implement a call to the Places Nearby Search API (type=pharmacy) "
            "using GOOGLE_PLACES_API_KEY here."
        )


def get_places_provider() -> PlacesProvider:
    settings = get_settings()
    if settings.PLACES_PROVIDER == "google_places" and settings.GOOGLE_PLACES_API_KEY:
        return GooglePlacesProvider()
    return MockPlacesProvider()
