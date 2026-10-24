"""Officer approval workflow: a generated challenge stays hidden from the customer until an officer releases it;
an officer can terminate the session at any time."""
import pytest
from asgiref.sync import sync_to_async

from tests.conftest import ensure_user, client_for, running_session
from tests.test_websocket import comm

S = "/api/v1/sessions"


def _pending(c, sid):
    r = c.post(f"{S}/{sid}/challenges")
    assert r.status_code == 201
    return r.json()


def test_challenge_is_hidden_until_the_officer_approves(make_client):
    c = make_client(require_challenge_approval=True)
    sid = running_session(c)
    body = _pending(c, sid)
    cid = body["id"]
    assert body["status"] == "awaiting_approval" and "challenge_type" not in body and "challenge_text" not in body
    # the customer cannot learn the content by any route, and cannot answer a challenge that was not released
    assert "challenge_text" not in c.get(f"{S}/{sid}/challenges").json()[0]
    cur = c.get(f"{S}/{sid}/challenges/current").json()["challenge"]
    assert cur["id"] == cid and "challenge_text" not in cur
    assert c.post(f"{S}/{sid}/challenges/{cid}/result", json={"measured": {"blink_count": 2}}).json()["error"]["code"] == "CHALLENGE_NOT_APPROVED"
    # the officer sees everything, and only an officer can approve
    item = c.officer.get("/api/v1/approvals/pending").json()["items"][0]
    assert item["challenge"]["id"] == cid and item["challenge"]["challenge_text"] and item["session"]["customer"] == "alice"
    assert c.post(f"{S}/{sid}/challenges/{cid}/approve").status_code == 403
    ok = c.officer.post(f"{S}/{sid}/challenges/{cid}/approve")
    assert ok.status_code == 200 and ok.json()["status"] == "issued" and ok.json()["approval_status"] == "approved"
    # now the customer sees it and can answer it
    cur = c.get(f"{S}/{sid}/challenges/current").json()["challenge"]
    assert cur["challenge_text"] and cur["status"] == "issued"
    assert c.officer.post(f"{S}/{sid}/challenges/{cid}/approve").json()["error"]["code"] == "CHALLENGE_NOT_PENDING"
    assert c.officer.get("/api/v1/approvals/pending").json()["items"] == []


def test_released_challenge_gets_a_fresh_time_window(make_client):
    from apps.challenges.models import Challenge
    from django.utils import timezone
    c = make_client(require_challenge_approval=True, challenge_ttl_seconds=60, challenge_approval_timeout_seconds=300)
    sid = running_session(c)
    cid = _pending(c, sid)["id"]
    before = Challenge.objects.get(pk=cid).expires_at
    c.officer.post(f"{S}/{sid}/challenges/{cid}/approve")
    after = Challenge.objects.get(pk=cid)
    assert after.approved_by.username == "olivia" and after.approved_at is not None
    assert (after.expires_at - timezone.now()).total_seconds() <= 60 < (before - timezone.now()).total_seconds()


def test_officer_can_regenerate_and_choose_the_type(make_client):
    from apps.challenges.models import Challenge
    c = make_client(require_challenge_approval=True)
    sid = running_session(c)
    old = _pending(c, sid)["id"]
    r = c.officer.post(f"{S}/{sid}/challenges/{old}/regenerate", json={"type": "blink"})
    assert r.status_code == 201 and r.json()["challenge_type"] == "blink" and r.json()["status"] == "awaiting_approval"
    assert Challenge.objects.get(pk=old).status == "expired"
    cur = c.get(f"{S}/{sid}/challenges/current").json()["challenge"]
    assert cur["id"] == r.json()["id"] and "challenge_text" not in cur       # still hidden from the customer
    assert c.officer.post(f"{S}/{sid}/challenges/{old}/approve").json()["error"]["code"] == "CHALLENGE_NOT_PENDING"
    assert c.officer.post(f"{S}/{sid}/challenges/{r.json()['id']}/regenerate", json={"type": "nonsense"}).status_code == 422


def test_officer_can_run_a_challenge_directly(make_client):
    c = make_client(require_challenge_approval=True)
    sid = running_session(c)
    r = c.officer.post(f"{S}/{sid}/challenges/issue", json={"type": "blink"})
    assert r.status_code == 201 and r.json()["status"] == "issued" and r.json()["challenge_type"] == "blink"
    cur = c.get(f"{S}/{sid}/challenges/current").json()["challenge"]
    assert cur["challenge_text"] == "Blink twice"
    a = c.post(f"{S}/{sid}/challenges/{cur['id']}/result", json={"measured": {"blink_count": 2}})
    assert a.status_code == 200 and "result" not in a.json()                  # the customer is not told the outcome
    seen = next(x for x in c.officer.get(f"{S}/{sid}/challenges").json() if x["id"] == cur["id"])
    assert seen["result"] == "passed"
    assert c.post(f"{S}/{sid}/challenges/issue", json={}).status_code == 403   # customers cannot


def test_approval_endpoints_need_a_running_session_and_the_right_ids(make_client):
    c = make_client(require_challenge_approval=True)
    sid = running_session(c)
    cid = _pending(c, sid)["id"]
    assert c.officer.post(f"{S}/{sid}/challenges/not-a-uuid/approve").status_code == 404
    assert c.officer.post(f"{S}/{sid}/challenges/00000000-0000-4000-8000-000000000000/approve").status_code == 404
    c.post(f"{S}/{sid}/complete")
    assert c.officer.post(f"{S}/{sid}/challenges/{cid}/approve").status_code == 409


def test_officer_can_terminate_at_any_time(make_client):
    from apps.challenges.models import Challenge
    c = make_client(require_challenge_approval=True)
    sid = running_session(c)
    cid = _pending(c, sid)["id"]
    assert c.post(f"{S}/{sid}/terminate", json={"reason": "x"}).status_code == 403           # customers cannot
    r = c.officer.post(f"{S}/{sid}/terminate", json={"reason": "Customer could not answer document questions"})
    assert r.status_code == 200 and r.json()["status"] == "terminated" and r.json()["termination_reason"].startswith("Customer could not")
    assert Challenge.objects.get(pk=cid).status == "expired"                                 # pending / issued challenges are closed
    assert c.get(f"{S}/{sid}").json()["status"] == "terminated"
    assert "final_risk_level" not in c.get(f"{S}/{sid}").json()                              # the customer is never told the risk
    # every customer action now fails cleanly
    assert c.post(f"{S}/{sid}/challenges").status_code == 409
    assert c.post(f"{S}/{sid}/challenges/{cid}/result", json={"measured": {}}).status_code == 409
    assert c.post(f"{S}/{sid}/complete").status_code == 409
    # evidence and a frozen report remain for the officers
    rep = c.officer.get(f"{S}/{sid}/report").json()
    assert rep["snapshot"] == "stored_at_completion" and rep["integrity"]["matches_evidence_chain"] is True
    assert any(t["event"] == "Session terminated by officer" for t in rep["timeline"])
    ev = c.officer.get(f"{S}/{sid}/evidence").json()
    assert ev["verification"]["valid"] is True and "session.terminated" in [e["event_type"] for e in ev["events"]]
    assert c.officer.post(f"{S}/{sid}/terminate", json={}).status_code == 409               # already ended


def test_terminate_works_before_the_live_step_and_without_a_reason(make_client):
    c = make_client()
    sid = c.post(S).json()["id"]
    r = c.officer.post(f"{S}/{sid}/terminate")
    assert r.status_code == 200 and r.json()["termination_reason"]


def test_officer_actions_are_audited(make_client):
    from apps.core.models import AuditLog
    c = make_client(require_challenge_approval=True)
    sid = running_session(c)
    cid = _pending(c, sid)["id"]
    c.officer.post(f"{S}/{sid}/challenges/{cid}/approve")
    c.officer.get(f"{S}/{sid}/report")
    c.officer.post(f"{S}/{sid}/terminate", json={"reason": "r"})
    actions = set(AuditLog.objects.filter(session_id=sid).values_list("action", flat=True))
    assert {"officer.approve_challenge", "officer.read_report", "officer.terminate_session"} <= actions
    assert AuditLog.objects.filter(action="officer.terminate_session").first().actor.username == "olivia"


@pytest.mark.django_db(transaction=True)
async def test_customer_socket_gets_the_challenge_only_after_approval(make_client):
    c = await sync_to_async(make_client)(require_challenge_approval=True)
    sid = await sync_to_async(running_session)(c)
    cust, off = comm(f"/ws/customer/{sid}", c.token), comm(f"/ws/sessions/{sid}", c.officer.token)
    assert (await cust.connect())[0] and (await off.connect())[0]
    assert (await cust.receive_json_from())["data"] == {"status": "running"}
    await off.receive_json_from()  # snapshot
    ch = (await sync_to_async(c.post)(f"{S}/{sid}/challenges")).json()
    msg = await off.receive_json_from()
    assert msg["event"] == "challenge.pending" and msg["data"]["challenge_text"] and msg["data"]["customer"] == "alice"
    assert await cust.receive_nothing()                      # nothing reaches the customer while it is pending
    await sync_to_async(c.officer.post)(f"{S}/{sid}/challenges/{ch['id']}/approve")
    released = await cust.receive_json_from()
    assert released["event"] == "challenge.released" and released["data"]["challenge_text"] and released["data"]["id"] == ch["id"]
    await sync_to_async(c.officer.post)(f"{S}/{sid}/terminate", json={"reason": "r"})
    seen = []
    while True:
        m = await cust.receive_json_from()
        seen.append(m)
        if m["event"] == "session.terminated":
            break
    assert "risk" not in str(seen).lower() and "final_risk_level" not in str(seen)       # the customer channel never carries risk data
    assert "We will complete it another way" in seen[-1]["data"]["message"]
    await cust.disconnect(), await off.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_customer_and_feed_sockets_are_access_controlled(make_client):
    c = await sync_to_async(make_client)()
    sid = (await sync_to_async(c.post)(S)).json()["id"]
    other = client_for(await sync_to_async(ensure_user)("bob", "customer"))
    assert not (await comm(f"/ws/customer/{sid}", c.officer.token).connect())[0]      # officers use the officer sockets
    assert not (await comm(f"/ws/customer/{sid}", other.token).connect())[0]          # another customer
    assert not (await comm(f"/ws/customer/{sid}", None).connect())[0]
    assert not (await comm(f"/ws/customer/{sid}", c.token, headers=[(b"origin", b"http://evil.example")]).connect())[0]
    assert not (await comm("/ws/officer/feed", c.token).connect())[0]                  # a customer cannot join the officer feed
    feed = comm("/ws/officer/feed", c.officer.token)
    assert (await feed.connect())[0]
    await sync_to_async(c.post)(f"{S}/{sid}/consent", json={"granted": True})
    assert (await feed.receive_json_from())["event"] == "session.status"
    await feed.disconnect()
