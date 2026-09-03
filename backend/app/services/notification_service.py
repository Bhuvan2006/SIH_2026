"""
Notification service for medication reminders.

Mock provider (default): logs the notification instead of sending it, and
keeps an in-memory list the API can expose for demo/testing purposes so
the reminder flow is visibly working without any SMS/push infra.

Msg91NotifierProvider sends real SMS texts via MSG91's Flow API -- India's
DLT (carrier) regulations require transactional SMS to use a pre-approved
template rather than arbitrary free text, so the whole reminder body is
passed as a single template variable (VAR1). WhatsApp/SMS fallback matters
a lot for reach with patients who don't keep the app open (see build plan
§6.5).
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import get_settings

logger = logging.getLogger("arogya.notifications")


@dataclass
class SentNotification:
    patient_id: str
    channel: str
    title: str
    body: str
    sent_at: datetime = field(default_factory=datetime.utcnow)


class NotifierProvider:
    def send(self, patient_id: str, phone: str | None, title: str, body: str) -> SentNotification:
        raise NotImplementedError


class MockNotifierProvider(NotifierProvider):
    def __init__(self) -> None:
        self.outbox: list[SentNotification] = []

    def send(self, patient_id: str, phone: str | None, title: str, body: str) -> SentNotification:
        note = SentNotification(patient_id=patient_id, channel="mock", title=title, body=body)
        self.outbox.append(note)
        logger.info("[MOCK NOTIFY] to=%s phone=%s title=%r body=%r", patient_id, phone, title, body)
        return note


def _to_msg91_mobile(phone: str) -> str:
    """
    MSG91 expects digits only, with country code and no "+"
    (e.g. "919812345678"). Strips spaces/dashes/parentheses/"+".
    """
    return re.sub(r"[^0-9]", "", phone)


class Msg91NotifierProvider(NotifierProvider):
    def __init__(self) -> None:
        settings = get_settings()
        if not (settings.MSG91_AUTH_KEY and settings.MSG91_FLOW_ID):
            raise RuntimeError(
                "NOTIFICATION_PROVIDER=msg91 requires MSG91_AUTH_KEY and MSG91_FLOW_ID "
                "to be set (create a DLT-approved Flow/template in the MSG91 dashboard first)."
            )
        self.auth_key = settings.MSG91_AUTH_KEY
        self.flow_id = settings.MSG91_FLOW_ID
        self.sender_id = settings.MSG91_SENDER_ID

    def send(self, patient_id: str, phone: str | None, title: str, body: str) -> SentNotification:
        note = SentNotification(patient_id=patient_id, channel="msg91_sms", title=title, body=body)
        if not phone:
            logger.warning("[MSG91] no phone on file for patient=%s, skipping SMS", patient_id)
            return note

        import httpx

        text = f"{title}: {body}" if title else body
        recipient: dict = {"mobiles": _to_msg91_mobile(phone), "VAR1": text}
        payload: dict = {"flow_id": self.flow_id, "recipients": [recipient]}
        if self.sender_id:
            payload["sender"] = self.sender_id

        try:
            response = httpx.post(
                "https://api.msg91.com/api/v5/flow/",
                headers={"Content-Type": "application/json", "authkey": self.auth_key},
                json=payload,
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("[MSG91] SMS sent to=%s response=%s", phone, response.text)
        except Exception:  # noqa: BLE001
            logger.exception("[MSG91] failed to send SMS to=%s", phone)
        return note


_mock_provider_singleton = MockNotifierProvider()
_msg91_provider_singleton: Msg91NotifierProvider | None = None


def get_notifier() -> NotifierProvider:
    settings = get_settings()
    if settings.NOTIFICATION_PROVIDER == "msg91":
        global _msg91_provider_singleton
        try:
            if _msg91_provider_singleton is None:
                _msg91_provider_singleton = Msg91NotifierProvider()
            return _msg91_provider_singleton
        except RuntimeError:
            logger.exception(
                "MSG91 provider misconfigured, falling back to mock notifier "
                "(reminders will still be logged, just not sent as real SMS)."
            )
            return _mock_provider_singleton
    if settings.NOTIFICATION_PROVIDER == "mock":
        return _mock_provider_singleton
    raise NotImplementedError(
        f"NOTIFICATION_PROVIDER='{settings.NOTIFICATION_PROVIDER}' is not implemented in this prototype."
    )
