"""API server used ONLY by the Playwright end-to-end suite (never imported by the real app).

It is the real application with two test conveniences that must not exist in production:
the WhatsApp sender is an in-memory mock, and ``/__e2e__/last-otp`` exposes the most recent OTP
sent to a number so the browser test can complete the OTP login.
"""

from __future__ import annotations

from app.api.routes.internal import get_sender
from app.core.config import get_settings
from app.main import create_app
from app.notifications import templates
from app.notifications.whatsapp import MockWhatsApp
from app.utils.phone import normalize_phone

app = create_app(get_settings())
_sender = MockWhatsApp()
app.dependency_overrides[get_sender] = lambda: _sender


@app.get("/__e2e__/last-otp")
async def last_otp(phone: str) -> dict[str, str | None]:
    target = normalize_phone(phone)
    for to, template, params in reversed(_sender.sent):
        if to == target and template == templates.OTP:
            return {"code": params[0]}
    return {"code": None}
