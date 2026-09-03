import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, chat, emergency, metrics, patients, pharmacies, prescriptions, prices, reminders, wellness, doctors, appointments
from app.core.config import get_settings
from app.db.database import Base, SessionLocal, engine
from app.db.seed import seed_if_empty
from app.scheduler.reminder_scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Arogya prototype API — multilingual prescription OCR, medication reminders, "
        "patient history, a grounded medical chatbot, price comparison, and a pharmacy locator. "
        "See /docs for interactive API documentation."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.ENV}


app.include_router(auth.router)
app.include_router(patients.router)
app.include_router(prescriptions.router)
app.include_router(reminders.router)
app.include_router(emergency.router)
app.include_router(metrics.router)
app.include_router(chat.router)
app.include_router(prices.router)
app.include_router(pharmacies.router)
app.include_router(wellness.router)
app.include_router(doctors.router)
app.include_router(appointments.router)
