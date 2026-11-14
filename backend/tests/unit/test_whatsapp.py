import hashlib
import hmac
import json
from datetime import timedelta

import httpx
import pytest

from app.core.config import Settings
from app.notifications import templates
from app.notifications.dispatcher import backoff_for
from app.notifications.webhook import verify_signature
from app.notifications.whatsapp import CloudWhatsApp, MockWhatsApp, SendError, build_sender

LIVE = Settings(_env_file=None, whatsapp_access_token="tok-secret", whatsapp_phone_number_id="1234")


def cloud(handler) -> CloudWhatsApp:
    return CloudWhatsApp(LIVE, transport=httpx.MockTransport(handler))


async def test_cloud_request_shape_and_message_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = (
            str(request.url),
            request.headers["authorization"],
            json.loads(request.content),
        )
        return httpx.Response(200, json={"messages": [{"id": "wamid.ABC"}]})

    mid = await cloud(handler).send_template("+919876543210", "appointment_reminder", ["Asha", "Dr. A"])
    assert mid == "wamid.ABC"
    assert seen["url"] == "https://graph.facebook.com/v21.0/1234/messages"
    assert seen["auth"] == "Bearer tok-secret"
    body = seen["body"]
    assert body["to"] == "919876543210" and body["type"] == "template"
    assert body["template"]["name"] == "appointment_reminder" and body["template"]["language"] == {"code": "en"}
    assert body["template"]["components"][0]["parameters"] == [
        {"type": "text", "text": "Asha"},
        {"type": "text", "text": "Dr. A"},
    ]


@pytest.mark.parametrize(
    ("status", "permanent"),
    [(400, True), (401, True), (403, True), (404, True), (429, False), (500, False), (503, False)],
)
async def test_cloud_error_classification_and_no_leaks(status, permanent):
    resp = httpx.Response(status, json={"error": {"code": 131030, "message": "to +919876543210 tok-secret"}})
    with pytest.raises(SendError) as e:
        await cloud(lambda r: resp).send_template("+919876543210", "t", [])
    assert e.value.permanent is permanent and e.value.http_status == status
    assert "tok-secret" not in str(e.value) and "9876543210" not in str(e.value)


async def test_cloud_network_and_malformed_responses_are_transient():
    def boom(request):
        raise httpx.ConnectTimeout("t", request=request)

    with pytest.raises(SendError) as e:
        await cloud(boom).send_template("+919876543210", "t", [])
    assert not e.value.permanent
    with pytest.raises(SendError) as e2:
        await cloud(lambda r: httpx.Response(200, json={"nope": 1})).send_template("+919876543210", "t", [])
    assert not e2.value.permanent
    with pytest.raises(SendError):
        await cloud(lambda r: httpx.Response(500, text="<html>")).send_template("+919876543210", "t", [])


async def test_mock_records_and_build_sender_chooses_mode():
    m = MockWhatsApp()
    assert (await m.send_template("+91", "t", ["a"])).startswith("mock-") and m.sent == [("+91", "t", ["a"])]
    assert build_sender(Settings(_env_file=None)) is build_sender(Settings(_env_file=None))
    assert isinstance(build_sender(LIVE), CloudWhatsApp)


def test_backoff_grows_and_caps():
    assert [backoff_for(i) for i in (1, 2, 3)] == [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15)]
    assert backoff_for(99) == timedelta(hours=6)


def test_signature_verification():
    body = b'{"a":1}'
    good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert verify_signature("s3cret", body, good)
    assert not verify_signature("s3cret", body + b" ", good)
    assert not verify_signature("other", body, good)
    assert not verify_signature("", body, good)  # unconfigured secret never validates
    assert not verify_signature("s3cret", body, None)
    assert not verify_signature("s3cret", body, good.removeprefix("sha256="))


def test_template_parameters_in_order_and_unknown_template():
    payload = {
        "patient_name": "Asha",
        "doctor_name": "Dr. A",
        "date": "02 Jan 2030",
        "time": "10:00 AM",
        "reference": "R1",
    }
    assert templates.body_parameters(templates.CONFIRMATION, payload) == [
        "Asha",
        "Dr. A",
        "02 Jan 2030",
        "10:00 AM",
        "R1",
    ]
    with pytest.raises(KeyError):
        templates.body_parameters("nope", payload)


async def test_cloud_otp_template_sends_code_in_body_and_button():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})

    await cloud(handler).send_template("+919876543210", templates.OTP, ["123456"], button_text="123456")
    body_c, button_c = seen["body"]["template"]["components"]
    assert body_c["parameters"] == [{"type": "text", "text": "123456"}]
    assert (
        button_c["type"] == "button" and button_c["sub_type"] == "url" and button_c["parameters"][0]["text"] == "123456"
    )
    assert templates.body_parameters(templates.OTP, {"code": "123456"}) == ["123456"]


def test_otp_hash_is_bound_to_challenge_phone_and_code():
    from cryptography.fernet import Fernet

    from app.core.security import FieldCipher

    c = FieldCipher(Fernet.generate_key().decode(), "k")
    base = c.hash_otp("id1", "ph", "123456")
    assert base == c.hash_otp("id1", "ph", "123456")
    assert (
        len(
            {
                base,
                c.hash_otp("id2", "ph", "123456"),
                c.hash_otp("id1", "p2", "123456"),
                c.hash_otp("id1", "ph", "123457"),
            }
        )
        == 4
    )
    assert c.hash_phone("ph") != c.hash_otp("", "ph", "")
