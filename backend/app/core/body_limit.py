"""Pure-ASGI request body cap that also covers chunked uploads (no Content-Length).

``Content-Length`` can be absent or lie, so the bytes actually received are counted. Once the cap is
exceeded the downstream app sees a disconnect and the client gets ``413`` (if nothing was sent yet).
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        received = 0
        exceeded = False
        started = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if exceeded and not started:
                return  # replaced below by the 413 response
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except Exception:
            if not exceeded:
                raise  # a disconnect we caused may surface as an error; anything else must propagate
        if exceeded and not started:
            body = json.dumps(
                {"error": {"code": "payload_too_large", "message": "Request body too large.", "request_id": None}}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                }
            )
            await send({"type": "http.response.body", "body": body})
