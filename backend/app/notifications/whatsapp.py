"""WhatsApp senders: a recording mock and the Cloud API adapter.

``CloudWhatsApp`` follows Meta's documented ``/{phone-number-id}/messages`` template payload but
has NOT been run against the real API (no credentials yet); it is tested with a fake transport only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.core.config import Settings


class SendError(Exception):
    """A failed send. ``permanent`` errors are never retried. Messages never contain PII or secrets."""

    def __init__(self, message: str, *, permanent: bool, code: str = "send_failed", http_status: int | None = None):
        super().__init__(message)
        self.permanent, self.code, self.http_status = permanent, code, http_status


class WhatsAppSender(Protocol):
    async def send_template(
        self, to_e164: str, template: str, params: list[str], button_text: str | None = None
    ) -> str:
        """Send an approved template; returns the provider message id."""
        ...


@dataclass
class MockWhatsApp:
    """Records messages in memory; nothing leaves the process."""

    sent: list[tuple[str, str, list[str]]] = field(default_factory=list)

    async def send_template(
        self, to_e164: str, template: str, params: list[str], button_text: str | None = None
    ) -> str:
        self.sent.append((to_e164, template, params))
        return f"mock-{uuid.uuid4().hex[:12]}"


class CloudWhatsApp:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = (
            f"https://graph.facebook.com/{settings.whatsapp_api_version}/{settings.whatsapp_phone_number_id}/messages"
        )
        self._token = settings.whatsapp_access_token.get_secret_value()
        self._language = settings.whatsapp_template_language
        self._timeout = settings.whatsapp_timeout_seconds
        self._transport = transport

    async def send_template(
        self, to_e164: str, template: str, params: list[str], button_text: str | None = None
    ) -> str:
        components: list[dict[str, object]] = [
            {"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}
        ]
        if button_text is not None:  # authentication templates carry the code in a copy-code button too
            components.append(
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [{"type": "text", "text": button_text}],
                }
            )
        body = {
            "messaging_product": "whatsapp",
            "to": to_e164.lstrip("+"),
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": self._language},
                "components": components,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(self._url, json=body, headers={"Authorization": f"Bearer {self._token}"})
        except httpx.HTTPError as exc:
            raise SendError("Network error contacting WhatsApp.", permanent=False, code="network_error") from exc
        if resp.status_code == 200:
            try:
                return str(resp.json()["messages"][0]["id"])
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                raise SendError("Unexpected WhatsApp response.", permanent=False, code="bad_response") from exc
        code = _error_code(resp)
        transient = resp.status_code in (408, 429) or resp.status_code >= 500
        raise SendError(
            f"WhatsApp rejected the message (HTTP {resp.status_code}, code {code}).",
            permanent=not transient,
            code=f"http_{resp.status_code}",
            http_status=resp.status_code,
        )


def _error_code(resp: httpx.Response) -> str:
    try:
        return str(resp.json()["error"]["code"])[:16]
    except (KeyError, ValueError, TypeError):
        return "unknown"


_mock = MockWhatsApp()


def build_sender(settings: Settings) -> WhatsAppSender:
    return CloudWhatsApp(settings) if settings.whatsapp_mode == "live" else _mock
