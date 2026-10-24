import threading

import pytest

from apps.evidence.models import EvidenceEvent
from apps.evidence.services import append_event
from apps.evidence.hashing import verify_chain
from tests.conftest import running_session


def _flow(c):
    sid = running_session(c)
    ch = c.post(f"/api/v1/sessions/{sid}/challenges").json()
    c.post(f"/api/v1/sessions/{sid}/challenges/{ch['id']}/result", json={"measured": {}})
    c.post(f"/api/v1/sessions/{sid}/complete")
    return sid


def test_chain_valid(client):
    sid = _flow(client)
    ev = client.officer.get(f"/api/v1/sessions/{sid}/evidence").json()
    assert len(ev["events"]) >= 5 and ev["verification"]["valid"] is True
    assert ev["events"][0]["previous_hash"] == "0" * 64 and ev["events"][1]["previous_hash"] == ev["events"][0]["event_hash"]
    assert client.officer.post(f"/api/v1/sessions/{sid}/evidence/verify").json()["valid"] is True


def test_modified_stored_event_detected(client):
    sid = _flow(client)
    EvidenceEvent.objects.filter(session_id=sid, seq=3).update(payload={"tampered": True})
    r = client.officer.post(f"/api/v1/sessions/{sid}/evidence/verify").json()
    assert r["valid"] is False and r["first_mismatch_seq"] == 3 and r["reason"] == "EVENT_HASH_MISMATCH"


def test_verify_supplied_packet_and_deleted_event(client):
    sid = _flow(client)
    events = client.officer.get(f"/api/v1/sessions/{sid}/evidence").json()["events"]
    assert client.officer.post(f"/api/v1/sessions/{sid}/evidence/verify", json={"events": events}).json()["valid"] is True
    del events[1]
    r = client.officer.post(f"/api/v1/sessions/{sid}/evidence/verify", json={"events": events}).json()
    assert r["valid"] is False and r["first_mismatch_index"] == 1


def test_export_content(client):
    sid = _flow(client)
    p = client.officer.get(f"/api/v1/sessions/{sid}/evidence/export").json()
    assert p["session"]["id"] == sid and p["hash_chain"]["verification"]["valid"] is True and "not legally certified" in p["disclaimer"]
    assert p["recommendation"]["human_review_required"] is True
    text = str(p).lower()
    assert "token" not in text and "image" not in text and "waveform" not in text


@pytest.mark.django_db(transaction=True)
def test_append_event_chain_valid_under_concurrent_writers(client):
    """Concurrent requests race for the same seq; the unique constraint plus retry must keep one valid chain."""
    from django.db import close_old_connections
    from tests.conftest import running_session  # noqa: F811
    sid = running_session(client)
    errors = []

    def worker(i):
        try:
            append_event(sid, "test.event", {"i": i})
        except Exception as e:  # pragma: no cover
            errors.append(e)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert client.officer.post(f"/api/v1/sessions/{sid}/evidence/verify").json()["valid"] is True
