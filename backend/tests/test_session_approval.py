"""A customer's request for a verification session goes to an officer first; only after approval can the customer begin."""
from tests.conftest import answer_challenge

S = "/api/v1/sessions"


def _request(c):
    r = c.post(S)
    assert r.status_code == 201, r.content
    return r.json()


def test_request_waits_for_an_officer(make_client):
    c = make_client(require_session_approval=True)
    s = _request(c)
    assert s["approval_status"] == "pending" and s["status"] == "awaiting_consent"
    sid = s["id"]
    for step, body in (("consent", {"granted": True}), ("start", None)):
        r = c.post(f"{S}/{sid}/{step}", json=body)
        assert r.status_code == 403 and r.json()["error"]["code"] == "APPROVAL_PENDING", step
    assert c.post(f"{S}/{sid}/challenges").status_code in (403, 409)          # nothing runs before approval
    queue = c.officer.get(f"{S}?approval=pending").json()
    assert queue["total"] == 1 and queue["items"][0]["id"] == sid and queue["items"][0]["customer"] == "alice"


def test_approval_then_consent_then_start(make_client):
    c = make_client(require_session_approval=True)
    sid = _request(c)["id"]
    assert c.post(f"{S}/{sid}/approve").status_code == 403                      # customers cannot approve themselves
    r = c.officer.post(f"{S}/{sid}/approve", json={"note": "Known customer"})
    assert r.status_code == 200 and r.json()["approval_status"] == "approved" and r.json()["approval_note"] == "Known customer"
    assert c.officer.post(f"{S}/{sid}/approve").status_code == 409              # already handled
    assert c.get(f"{S}/{sid}").json()["approval_status"] == "approved"
    assert "approval_note" not in c.get(f"{S}/{sid}").json()                    # the officer's note stays with the officers
    assert c.post(f"{S}/{sid}/consent", json={"granted": True}).json()["status"] == "ready"
    assert c.post(f"{S}/{sid}/start").json()["status"] == "running"
    assert c.post(f"{S}/{sid}/challenges").status_code == 201


def test_rejection_is_final_and_the_reason_stays_private(make_client):
    c = make_client(require_session_approval=True)
    sid = _request(c)["id"]
    r = c.officer.post(f"{S}/{sid}/reject", json={"reason": "Name does not match our records"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["approval_status"] == "rejected"
    mine = c.get(f"{S}/{sid}").json()
    assert mine["approval_status"] == "rejected" and "Name does not match" not in str(mine)
    err = c.post(f"{S}/{sid}/consent", json={"granted": True})
    assert err.status_code == 403 and err.json()["error"]["code"] == "APPROVAL_REJECTED"
    assert c.officer.post(f"{S}/{sid}/approve").status_code == 409              # a rejected request cannot be approved later
    assert c.officer.post(f"{S}/{sid}/reject").status_code == 409


def test_unanswered_request_expires(make_client):
    c = make_client(require_session_approval=True, session_approval_timeout_seconds=0)
    sid = _request(c)["id"]
    r = c.post(f"{S}/{sid}/consent", json={"granted": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "APPROVAL_EXPIRED"
    assert c.officer.post(f"{S}/{sid}/approve").status_code == 409


def test_a_customer_cannot_flood_the_officer_queue(make_client):
    c = make_client(require_session_approval=True)
    for _ in range(3):
        _request(c)
    r = c.post(S)
    assert r.status_code == 429 and r.json()["error"]["code"] == "TOO_MANY_PENDING"
    assert c.officer.get(f"{S}?approval=pending").json()["total"] == 3


def test_approval_filter_is_validated(make_client):
    c = make_client(require_session_approval=True)
    assert c.officer.get(f"{S}?approval=bogus").status_code == 422


def test_approval_can_be_switched_off(make_client):
    c = make_client(require_session_approval=False)
    s = _request(c)
    assert s["approval_status"] == "not_required"
    assert c.post(f"{S}/{s['id']}/consent", json={"granted": True}).status_code == 200


def test_unknown_session_for_approval_endpoints(make_client):
    c = make_client(require_session_approval=True)
    assert c.officer.post(f"{S}/not-a-uuid/approve").status_code == 404
    assert c.officer.post(f"{S}/00000000-0000-4000-8000-000000000000/reject").status_code == 404


def test_auto_approve_releases_waiting_and_future_challenges(make_client):
    c = make_client(require_session_approval=True, require_challenge_approval=True)
    sid = _request(c)["id"]
    c.officer.post(f"{S}/{sid}/approve")
    c.post(f"{S}/{sid}/consent", json={"granted": True})
    c.post(f"{S}/{sid}/start")
    first = c.post(f"{S}/{sid}/challenges").json()
    assert first["status"] == "awaiting_approval" and "challenge_text" not in first        # hidden until an officer clicks
    on = c.officer.post(f"{S}/{sid}/auto-approve", json={"enabled": True})
    assert on.status_code == 200 and on.json()["challenge_auto_approve"] is True
    cur = c.get(f"{S}/{sid}/challenges/current").json()["challenge"]
    assert cur["id"] == first["id"] and cur["status"] == "issued" and cur["challenge_text"]     # released by the switch
    assert c.post(f"{S}/{sid}/challenges/{cur['id']}/result", json={"measured": {}}).status_code == 200
    nxt = c.post(f"{S}/{sid}/challenges").json()
    assert nxt["status"] == "issued" and nxt["challenge_text"]                             # later ones need no click
    assert c.post(f"{S}/{sid}/auto-approve", json={"enabled": False}).status_code == 403


def test_officer_report_covers_the_approval_step(make_client):
    c = make_client(require_session_approval=True)
    sid = _request(c)["id"]
    c.officer.post(f"{S}/{sid}/approve")
    c.post(f"{S}/{sid}/consent", json={"granted": True})
    c.post(f"{S}/{sid}/start")
    answer_challenge(c, sid, "blink", {"blink_count": 2})
    c.post(f"{S}/{sid}/complete")
    events = [e["event_type"] for e in c.officer.get(f"{S}/{sid}/evidence").json()["events"]]
    assert events[:3] == ["session.created", "session.approval_requested", "session.approved"]


def test_challenges_the_customer_never_saw_do_not_count_as_ignored(make_client):
    """A challenge an officer replaced (or that nobody released) was never shown, so it must not look like a missed request."""
    from apps.decision_engine.services import collect_inputs
    from apps.verification.models import VerificationSession
    c = make_client(require_challenge_approval=True)
    from tests.conftest import running_session
    sid = running_session(c)
    first = c.post(f"{S}/{sid}/challenges").json()
    assert c.officer.post(f"{S}/{sid}/challenges/{first['id']}/regenerate", json={"type": "blink"}).status_code == 201
    chs = collect_inputs(VerificationSession.objects.get(pk=sid))["challenges"]
    replaced = next(x for x in chs if x["status"] == "expired")
    assert replaced["never_released"] is True
