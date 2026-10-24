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


def test_call_id_is_relayed_only_when_valid():
    cid = "0f8e2c1a-1111-4222-8333-944455556666"
    assert clean_message({"event": "call.request", "data": {"call_id": cid}}) == ("call.request", {"reason": "", "call_id": cid})
    assert clean_message({"event": "rtc.signal", "data": {"kind": "answer", "sdp": "v=0", "call_id": cid}})[1]["call_id"] == cid
    ev, d = clean_message({"event": "rtc.signal", "data": {"kind": "candidate", "candidate": None, "call_id": cid}})
    assert d == {"kind": "candidate", "candidate": None, "call_id": cid}
    for bad in ("short", "x" * 41, "has space here!", 12345, None, "<script>alert(1)</script>"):
        out = clean_message({"event": "call.accept", "data": {"call_id": bad}})
        assert out == ("call.accept", {"reason": ""}), bad                    # invalid ids are dropped, never forwarded


@pytest.mark.django_db(transaction=True)
async def test_call_messages_never_reach_another_session(client):
    """Officer of session A calls; the customer of session B (same customer account, different session) receives nothing."""
    from tests.conftest import running_session
    a = await sync_to_async(running_session)(client)
    b = await sync_to_async(running_session)(client)
    officer_a = comm(f"/ws/sessions/{a}", client.officer.token)
    cust_a, cust_b = comm(f"/ws/customer/{a}", client.token), comm(f"/ws/customer/{b}", client.token)
    for w in (officer_a, cust_a, cust_b):
        assert (await w.connect())[0]
        await w.receive_json_from()
    await officer_a.send_json_to({"event": "call.request", "data": {"call_id": "abcdef12-0000-4000-8000-000000000000"}})
    m = await cust_a.receive_json_from()
    assert m["event"] == "call.request" and m["session_id"] == a and m["data"]["call_id"].startswith("abcdef12")
    assert await cust_b.receive_nothing()
    await cust_a.send_json_to({"event": "rtc.signal", "data": {"kind": "answer", "sdp": "v=0", "call_id": "abcdef12-0000-4000-8000-000000000000"}})
    got = await officer_a.receive_json_from()
    assert got["event"] == "rtc.signal" and got["data"]["from"] == "customer" and got["session_id"] == a
    for w in (officer_a, cust_a, cust_b):
        await w.disconnect()
