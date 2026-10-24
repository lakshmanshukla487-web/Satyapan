import pytest
from asgiref.sync import sync_to_async

from apps.realtime.relay import Bucket, clean_message
from tests.test_websocket import comm


def test_clean_message_whitelists_and_limits():
    assert clean_message({"event": "chat.message", "data": {"text": "  hello  ", "evil": 1}}) == ("chat.message", {"text": "hello"})
    assert clean_message({"event": "chat.message", "data": {"text": "x" * 501}}) is None
    assert clean_message({"event": "chat.message", "data": {"text": "   "}}) is None
    assert clean_message({"event": "session.terminated", "data": {}}) is None  # only call/chat events can be relayed
    assert clean_message({"event": "rtc.signal", "data": {"kind": "offer", "sdp": "v=0..."}}) == ("rtc.signal", {"kind": "offer", "sdp": "v=0..."})
    assert clean_message({"event": "rtc.signal", "data": {"kind": "offer", "sdp": "x" * 20000}}) is None
    assert clean_message({"event": "rtc.signal", "data": {"kind": "answer"}}) is None
    ev, d = clean_message({"event": "rtc.signal", "data": {"kind": "candidate", "candidate": {"candidate": "candidate:1 ...", "sdpMid": "0", "sdpMLineIndex": 0, "x": 1}}})
    assert d["candidate"] == {"candidate": "candidate:1 ...", "sdpMid": "0", "sdpMLineIndex": 0}
    assert clean_message({"event": "rtc.signal", "data": {"kind": "candidate", "candidate": "str"}}) is None
    assert clean_message("nope") is None and clean_message({"event": "call.request", "data": "x"}) == ("call.request", {"reason": ""})


def test_bucket_limits_bursts():
    b = Bucket(rate=0.0001, burst=3)
    assert [b.take() for _ in range(5)] == [True, True, True, False, False]


@pytest.mark.django_db(transaction=True)
async def test_call_and_chat_relay_between_officer_and_customer(client):
    from tests.conftest import running_session
    sid = await sync_to_async(running_session)(client)
    officer = comm(f"/ws/sessions/{sid}", client.officer.token)
    customer = comm(f"/ws/customer/{sid}", client.token)
    assert (await officer.connect())[0] and (await customer.connect())[0]
    await officer.receive_json_from(), await customer.receive_json_from()  # initial session.status
    await officer.send_json_to({"event": "call.request", "data": {}})
    m = await customer.receive_json_from()
    assert m["event"] == "call.request" and m["data"]["from"] == "officer"
    await customer.send_json_to({"event": "call.accept", "data": {}})
    assert (await officer.receive_json_from())["event"] == "call.accept"
    await officer.send_json_to({"event": "rtc.signal", "data": {"kind": "offer", "sdp": "v=0"}})
    assert (await customer.receive_json_from())["data"]["kind"] == "offer"
    await customer.send_json_to({"event": "chat.message", "data": {"text": "hi officer", "role": "officer"}})
    c = await officer.receive_json_from()
    assert c["data"] == {"text": "hi officer", "from": "customer"}  # sender role is set by the server, not by the client
    await officer.send_json_to({"event": "risk.updated", "data": {"risk": "RED"}})  # not a relayable event
    assert await customer.receive_nothing()
    await officer.disconnect(), await customer.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_relay_refused_when_session_not_running(client):
    sid = (await sync_to_async(client.post)("/api/v1/sessions")).json()["id"]  # created, not running
    officer = comm(f"/ws/sessions/{sid}", client.officer.token)
    customer = comm(f"/ws/customer/{sid}", client.token)
    assert (await officer.connect())[0] and (await customer.connect())[0]
    await officer.receive_json_from(), await customer.receive_json_from()
    await officer.send_json_to({"event": "call.request", "data": {}})
    assert (await officer.receive_json_from())["data"]["code"] == "SESSION_NOT_RUNNING"
    assert await customer.receive_nothing()
    await officer.disconnect(), await customer.disconnect()


def test_rtc_config_lists_ice_servers(make_client):
    c = make_client(None, stun_urls="stun:a.example:3478", turn_urls="turn:t.example:3478", turn_username="u", turn_credential="p")
    d = c.get("/api/v1/rtc/config").json()
    assert d["enabled"] and d["relayConfigured"] and d["iceServers"][0]["urls"] == ["stun:a.example:3478"] and d["iceServers"][1]["username"] == "u"
