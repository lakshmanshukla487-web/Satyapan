import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator

from satyapan.asgi import application
from tests.conftest import make_settings  # noqa: F401

ORIGIN = [(b"origin", b"http://localhost:5173")]


def comm(path, token, headers=ORIGIN):
    return WebsocketCommunicator(application, path, headers=headers, subprotocols=["satyapan.v1", token] if token else ["satyapan.v1"])


@pytest.mark.django_db(transaction=True)
async def test_websocket_events_and_isolation(client):
    post = sync_to_async(client.post)
    a, b = (await post("/api/v1/sessions")).json()["id"], (await post("/api/v1/sessions")).json()["id"]
    tok = client.officer.token
    wa, wb = comm(f"/ws/sessions/{a}", tok), comm(f"/ws/sessions/{b}", tok)
    assert (await wa.connect())[0] and (await wb.connect())[0]
    assert (await wa.receive_json_from())["event"] == "session.status"
    assert (await wb.receive_json_from())["event"] == "session.status"
    await post(f"/api/v1/sessions/{a}/consent", json={"granted": True})
    m = await wa.receive_json_from()
    assert m["event"] == "session.status" and m["session_id"] == a and m["data"]["status"] == "ready" and m["timestamp"].endswith("Z")
    await post(f"/api/v1/sessions/{b}/cancel")
    assert (await wb.receive_json_from())["data"]["status"] == "cancelled"  # b only sees its own event
    assert await wa.receive_nothing()  # and a saw nothing of b's cancellation
    await wa.disconnect(), await wb.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_websocket_rejects_unknown_session_and_foreign_origin(client):
    tok = client.officer.token
    connected, _ = await comm("/ws/sessions/unknown", tok).connect()
    assert not connected
    connected, _ = await comm("/ws/sessions/00000000-0000-4000-8000-000000000000", tok).connect()
    assert not connected
    sid = (await sync_to_async(client.post)("/api/v1/sessions")).json()["id"]
    connected, _ = await comm(f"/ws/sessions/{sid}", tok, headers=[(b"origin", b"http://evil.example")]).connect()
    assert not connected


@pytest.mark.django_db(transaction=True)
async def test_websocket_requires_an_officer_token(client):
    sid = (await sync_to_async(client.post)("/api/v1/sessions")).json()["id"]
    path = f"/ws/sessions/{sid}"
    assert not (await comm(path, None).connect())[0]  # no token
    assert not (await comm(path, "garbage").connect())[0]  # invalid token
    assert not (await comm(path, client.token).connect())[0]  # a customer, even the session's own owner, gets no live risk events
    ok = comm(path, client.officer.token)
    connected, subprotocol = await ok.connect()
    assert connected and subprotocol == "satyapan.v1"  # token is never echoed back
    await ok.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_detector_events_stream_over_websocket(make_client):
    from tests.conftest import MockDetector, png_bytes, running_session
    c = await sync_to_async(make_client)(lambda s: {"vit": MockDetector(s, "vit", "visual_deepfake", 0.1)})
    sid = await sync_to_async(running_session)(c)
    ws = comm(f"/ws/sessions/{sid}", c.officer.token)
    await ws.connect()
    await ws.receive_json_from()
    r = await sync_to_async(c.post)(f"/api/v1/sessions/{sid}/analysis/frame", files={"file": ("f.png", png_bytes(), "image/png")})
    assert r.status_code == 200
    events = []
    while not await ws.receive_nothing():
        events.append((await ws.receive_json_from())["event"])
    assert events[:3] == ["detector.started", "detector.completed", "signal.updated"] and events[-1] == "risk.updated"
    await ws.disconnect()
