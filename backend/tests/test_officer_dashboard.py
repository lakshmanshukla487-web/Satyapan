"""The officer console in one request (it used to take 5 requests per session) and the bounded evidence tail."""
from tests.conftest import answer_challenge, running_session

S = "/api/v1/sessions"


def test_dashboard_returns_everything_in_one_response(client):
    sid = running_session(client)
    answer_challenge(client, sid, "blink")
    client.post(S)  # a second, not started session
    d = client.officer.get("/api/v1/officer/dashboard").json()
    assert d["total"] == 2 and len(d["sessions"]) == 2
    row = next(x for x in d["sessions"] if x["id"] == sid)
    assert row["customer"] == "alice" and row["status"] == "running" and row["tier"] in ("GREEN", "AMBER", "RED", "GREY")
    assert row["documents_status"] == "not_submitted" and row["signals_total"] == 10 and isinstance(row["signals_ok"], int)
    assert set(d) >= {"sessions", "total", "pending_approvals", "pending_requests", "activity"}
    assert d["activity"] and all(a["session_id"] in {x["id"] for x in d["sessions"]} for a in d["activity"])


def test_dashboard_is_officer_only(client):
    assert client.get("/api/v1/officer/dashboard").status_code == 403
    assert client.__class__().get("/api/v1/officer/dashboard").status_code == 401


def test_dashboard_lists_pending_requests_and_approvals(make_client):
    c = make_client(require_session_approval=True, require_challenge_approval=True)
    sid = c.post(S).json()["id"]
    d = c.officer.get("/api/v1/officer/dashboard").json()
    assert [r["id"] for r in d["pending_requests"]] == [sid]
    c.officer.post(f"{S}/{sid}/approve", json={})
    c.post(f"{S}/{sid}/consent", json={"granted": True}), c.post(f"{S}/{sid}/start")
    ch = c.post(f"{S}/{sid}/challenges").json()
    d = c.officer.get("/api/v1/officer/dashboard").json()
    assert d["pending_requests"] == [] and [p["challenge"]["id"] for p in d["pending_approvals"]] == [ch["id"]]
    assert d["pending_approvals"][0]["session"]["id"] == sid


def test_evidence_tail_is_bounded_and_not_audited(client):
    from apps.core.models import AuditLog
    sid = running_session(client)
    for _ in range(3):
        answer_challenge(client, sid, "blink")
    full = client.officer.get(f"{S}/{sid}/evidence").json()
    tail = client.officer.get(f"{S}/{sid}/evidence?tail=3").json()
    assert len(tail["events"]) == 3 and tail["events"] == full["events"][-3:] and tail["partial"] is True and tail["total"] == len(full["events"])
    assert client.officer.get(f"{S}/{sid}/evidence?tail=0").status_code == 422 and client.officer.get(f"{S}/{sid}/evidence?tail=x").status_code == 422
    reads = AuditLog.objects.filter(action="officer.read_evidence").count()
    client.officer.get(f"{S}/{sid}/evidence?tail=5")
    assert AuditLog.objects.filter(action="officer.read_evidence").count() == reads  # live polling does not flood the audit log
