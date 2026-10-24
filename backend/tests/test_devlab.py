"""Developer role and the developer model test lab: authorisation, real-detector path, honest unavailability, validation,
isolation from customer sessions, metrics, datasets, cancellation and clean-up."""
import io
import os
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.core.cache import InferenceGate
from apps.devlab import metrics
from apps.devlab.models import DevTestItem, DevTestJob
from tests.conftest import Client, MockDetector, client_for, ensure_user, png_bytes, wav_bytes

D = "/api/v1/devlab"


@pytest.fixture
def lab(make_client, tmp_path):
    """A developer client with mock vit/audio detectors (no ML packages needed) and isolated storage."""
    def _make(detectors=None, **kw):
        dets = detectors or (lambda s: {"vit": MockDetector(s, "vit", "visual_deepfake", 0.9), "audio": MockDetector(s, "audio", "audio_spoof", 0.1)})
        c = make_client(dets, devlab_storage_dir=str(tmp_path / "devlab"), devlab_run_inline=True, **kw)
        c.dev = client_for(ensure_user("devon", "developer"))
        c.tmp = tmp_path
        return c
    return _make


def new_job(dev, **opts):
    r = dev.post(f"{D}/jobs", json={"source": "upload", "name": "t", **opts})
    assert r.status_code == 201, r.content
    return r.json()["id"]


def add(dev, jid, name, data, ctype="application/octet-stream", label=""):
    return dev.post(f"{D}/jobs/{jid}/items", files={"file": (name, data, ctype)}, fields={"label": label})


def run(dev, jid):
    r = dev.post(f"{D}/jobs/{jid}/start")
    assert r.status_code == 200, r.content
    return dev.get(f"{D}/jobs/{jid}").json()


# ---- authorisation ----------------------------------------------------------------------------------------------------------------

def test_only_developer_accounts_reach_the_lab(lab):
    c = lab()
    assert c.dev.get(f"{D}/models").status_code == 200
    for who in (c, c.officer):
        r = who.get(f"{D}/models")
        assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
        assert who.post(f"{D}/jobs", json={"source": "upload"}).status_code == 403
    assert Client().get(f"{D}/models").status_code == 401
    assert Client().get(f"{D}/jobs").status_code == 401


def test_developer_cannot_run_or_review_customer_sessions(lab):
    c = lab()
    sid = c.post("/api/v1/sessions").json()["id"]
    assert c.dev.post("/api/v1/sessions").status_code == 403                   # never creates a real customer session
    assert c.dev.get("/api/v1/sessions").json()["total"] == 0                  # sees no customer's session
    assert c.dev.get(f"/api/v1/sessions/{sid}").status_code == 404
    assert c.dev.get("/api/v1/officer/dashboard").status_code == 403
    assert c.dev.get(f"/api/v1/sessions/{sid}/analysis").status_code == 403
    assert c.dev.post(f"/api/v1/sessions/{sid}/consent", json={"granted": True}).status_code == 403


def test_public_registration_can_never_create_a_developer(lab):
    lab()
    r = Client().post("/api/v1/auth/register", json={"username": "wannabe", "password": "a-strong-pass-77", "role": "developer"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "customer"


def test_create_developer_command(db, monkeypatch):
    from apps.accounts.models import User
    monkeypatch.setattr("sys.stdin", io.StringIO("a-strong-pass-77\n"))
    call_command("create_developer", "Dev.One", "--password-stdin")
    u = User.objects.get(username="dev.one")
    assert u.role == "developer" and u.check_password("a-strong-pass-77")
    ensure_user("cust", "customer")
    monkeypatch.setattr("sys.stdin", io.StringIO("a-strong-pass-77\n"))
    with pytest.raises(Exception):
        call_command("create_developer", "cust", "--password-stdin")           # an existing customer is not converted silently
    assert User.objects.get(username="cust").role == "customer"
    monkeypatch.setattr("sys.stdin", io.StringIO("123\n"))
    with pytest.raises(Exception):
        call_command("create_developer", "dev.two", "--password-stdin")        # weak password refused
    epoch = u.token_epoch
    call_command("create_developer", "dev.one", "--revoke")
    u.refresh_from_db()
    assert u.role == "customer" and u.token_epoch == epoch + 1                  # every open sign-in ends


def test_role_field_accepts_developer_without_touching_existing_accounts(db):
    from apps.accounts.models import User
    field = User._meta.get_field("role")
    assert ("developer", "Developer") in field.choices and field.max_length >= len("developer")
    assert {c for c, _ in field.choices} >= {"customer", "officer"}


# ---- running tests ----------------------------------------------------------------------------------------------------------------

def test_image_and_audio_run_through_the_detectors_and_stay_isolated(lab):
    from apps.core.models import AuditLog
    from apps.evidence.models import EvidenceEvent
    from apps.signals.models import DetectorSignal
    from apps.verification.models import VerificationSession
    c = lab()
    jid = new_job(c.dev)
    a = add(c.dev, jid, "face.png", png_bytes(), "image/png", "fake")
    b = add(c.dev, jid, "voice.wav", wav_bytes(2.0), "audio/wav", "real")
    assert a.status_code == b.status_code == 201, (a.content, b.content)
    assert a.json()["media_type"] == "image" and b.json()["media_type"] == "audio"
    d = run(c.dev, jid)
    assert d["job"]["status"] == "completed" and d["job"]["finished_items"] == 2
    img, aud = d["items"]
    assert img["status"] == "done" and img["detector"] == "vit" and img["score"] == 0.9 and img["threshold"] == 0.7 and img["prediction"] == "fake" and img["correct"] is True
    assert aud["status"] == "done" and aud["detector"] == "audio" and aud["score"] == 0.1 and aud["prediction"] == "real" and aud["correct"] is True
    assert img["duration_ms"] is not None and img["frames_analyzed"] == 1
    groups = {(m["media_type"], m["detector"]): m for m in d["metrics"]}
    assert groups[("image", "vit")]["available"] and groups[("image", "vit")]["true_positive"] == 1
    assert groups[("audio", "audio")]["true_negative"] == 1
    # isolation: nothing was written to the customer-verification side
    assert VerificationSession.objects.count() == 0 and DetectorSignal.objects.count() == 0 and EvidenceEvent.objects.count() == 0
    assert not AuditLog.objects.filter(session_id__isnull=False).exists()
    # temporary uploads are gone once processed
    assert not any(p.is_file() for p in (c.tmp / "devlab").rglob("*"))
    assert all(it.stored_path == "" for it in DevTestItem.objects.filter(job_id=jid))


def test_missing_or_disabled_model_is_reported_never_faked(lab):
    c = lab(lambda s: {"vit": MockDetector(s, "vit", "visual_deepfake", 0.9, fail_load="MODEL_NOT_DOWNLOADED")})  # no audio detector at all
    jid = new_job(c.dev)
    add(c.dev, jid, "face.png", png_bytes(), "image/png", "fake")
    add(c.dev, jid, "voice.wav", wav_bytes(2.0), "audio/wav", "real")
    img, aud = run(c.dev, jid)["items"]
    assert img["status"] == "unavailable" and img["error_code"] == "MODEL_NOT_DOWNLOADED" and img["score"] is None and img["prediction"] == ""
    assert aud["status"] == "unavailable" and aud["error_code"] == "DETECTOR_DISABLED" and aud["score"] is None
    m = run_metrics = c.dev.get(f"{D}/jobs/{jid}").json()["metrics"]
    assert all(not g["available"] and g["evaluated"] == 0 for g in m)
    assert any(e["reason"] == "unavailable" for e in run_metrics[0]["excluded"])
    health = {d["name"]: d for d in c.dev.get(f"{D}/models").json()["detectors"]}
    assert health["audio"]["inference"] == "disabled" and health["vit"]["inference"] == "unavailable" and health["vit"]["error_code"] == "MODEL_NOT_DOWNLOADED"


def test_uploads_are_validated_by_content(lab):
    c = lab(devlab_max_audio_seconds=1)
    jid = new_job(c.dev)
    r = add(c.dev, jid, "x.gif", b"GIF89a" + b"\0" * 64, "image/gif")
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_MEDIA"
    r = add(c.dev, jid, "sneaky.wav", png_bytes(), "audio/wav")                # client MIME and name say audio, content is a PNG
    assert r.status_code == 415 and r.json()["error"]["code"] == "MEDIA_TYPE_MISMATCH"
    r = add(c.dev, jid, "long.wav", wav_bytes(2.0), "audio/wav")
    assert r.status_code == 422 and r.json()["error"]["code"] == "AUDIO_TOO_LONG"
    assert add(c.dev, jid, "a.png", png_bytes(), "image/png", "maybe").status_code == 422
    assert add(c.dev, jid, "broken.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 40, "image/png").status_code == 422
    assert DevTestItem.objects.filter(job_id=jid).count() == 0
    assert not any(p.is_file() for p in (c.tmp / "devlab").rglob("*"))         # rejected files are not kept
    assert c.dev.post(f"{D}/jobs/{jid}/start").status_code == 422              # nothing to run


def test_low_quality_input_follows_the_live_rule_unless_asked(lab):
    c = lab()
    jid = new_job(c.dev)
    add(c.dev, jid, "tiny.png", png_bytes((32, 32)), "image/png")
    it = run(c.dev, jid)["items"][0]
    assert it["status"] == "low_quality" and it["score"] is None and "SMALL_IMAGE" in it["warnings"]
    jid2 = new_job(c.dev, score_low_quality=True)
    add(c.dev, jid2, "tiny.png", png_bytes((32, 32)), "image/png")
    it2 = run(c.dev, jid2)["items"][0]
    assert it2["status"] == "done" and it2["score"] == 0.9 and "SMALL_IMAGE" in it2["warnings"]


def test_jobs_are_private_and_editable_only_as_drafts(lab):
    c = lab()
    jid = new_job(c.dev)
    other = client_for(ensure_user("devora", "developer"))
    assert other.get(f"{D}/jobs/{jid}").status_code == 404
    assert other.post(f"{D}/jobs/{jid}/delete").status_code == 404
    assert c.dev.get(f"{D}/jobs/not-a-uuid").status_code == 404
    add(c.dev, jid, "a.png", png_bytes(), "image/png")
    run(c.dev, jid)
    assert add(c.dev, jid, "b.png", png_bytes(), "image/png").status_code == 409
    assert c.dev.post(f"{D}/jobs/{jid}/start").status_code == 409


def test_cancel_and_delete_clean_up(lab):
    c = lab()
    jid = new_job(c.dev)
    add(c.dev, jid, "a.png", png_bytes(), "image/png")
    add(c.dev, jid, "b.png", png_bytes(), "image/png")
    assert sum(1 for p in (c.tmp / "devlab").rglob("*") if p.is_file()) == 2
    j = c.dev.post(f"{D}/jobs/{jid}/cancel").json()
    assert j["status"] == "cancelled" and j["counts"] == {"cancelled": 2}
    assert not any(p.is_file() for p in (c.tmp / "devlab").rglob("*"))
    assert c.dev.post(f"{D}/jobs/{jid}/delete").json() == {"deleted": True}
    assert not DevTestJob.objects.filter(pk=jid).exists() and not DevTestItem.objects.filter(job_id=jid).exists()


def test_a_running_job_stops_at_the_next_item_when_cancelled(lab, monkeypatch):
    from apps.devlab import runner
    c = lab()
    jid = new_job(c.dev)
    for i in range(3):
        add(c.dev, jid, f"{i}.png", png_bytes(), "image/png")
    real = runner.process_item

    def first_then_cancel(rt, job, it, stop):
        out = real(rt, job, it, stop)
        DevTestJob.objects.filter(pk=job.pk).update(cancel_requested=True)  # the developer pressed Cancel during item 1
        return out
    monkeypatch.setattr(runner, "process_item", first_then_cancel)
    d = run(c.dev, jid)
    assert d["job"]["status"] == "cancelled" and [it["status"] for it in d["items"]] == ["done", "cancelled", "cancelled"]
    assert not any(p.is_file() for p in (c.tmp / "devlab").rglob("*"))


def test_active_job_limit_and_stale_worker_recovery(lab):
    from apps.accounts.models import User
    from apps.devlab import runner
    c = lab(devlab_max_active_jobs=1)
    dev = User.objects.get(username="devon")
    DevTestJob.objects.create(owner=dev, status="running", heartbeat_at=timezone.now())
    jid = new_job(c.dev)
    add(c.dev, jid, "a.png", png_bytes(), "image/png")
    r = c.dev.post(f"{D}/jobs/{jid}/start")
    assert r.status_code == 409 and r.json()["error"]["code"] == "TOO_MANY_ACTIVE_JOBS"
    stale = DevTestJob.objects.create(owner=dev, status="running", heartbeat_at=timezone.now() - timedelta(hours=1))
    runner.recover_stale(owner=dev)
    stale.refresh_from_db()
    assert stale.status == "failed" and "interrupted" in stale.error


def test_export_guards_against_spreadsheet_formulas(lab):
    c = lab()
    jid = new_job(c.dev)
    add(c.dev, jid, "=HYPERLINK(evil).png", png_bytes(), "image/png", "fake")
    run(c.dev, jid)
    r = c.dev._c.get(f"{D}/jobs/{jid}/export?format=csv")
    body = r.content.decode()
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv") and "'=HYPERLINK(evil).png" in body and "0.9" in body
    assert c.dev._c.get(f"{D}/jobs/{jid}/export?format=json").status_code == 200
    assert c.dev._c.get(f"{D}/jobs/{jid}/export?format=xml").status_code == 422


def test_local_dataset_with_folder_labels(lab, tmp_path):
    root = tmp_path / "datasets"
    (root / "faces" / "real").mkdir(parents=True)
    (root / "faces" / "fake").mkdir(parents=True)
    (root / "faces" / "real" / "r1.png").write_bytes(png_bytes())
    (root / "faces" / "fake" / "f1.png").write_bytes(png_bytes())
    (root / "faces" / "fake" / "f2.png").write_bytes(png_bytes())
    (root / "faces" / "notes.txt").write_text("ignored")
    secret = tmp_path / "secret.png"
    secret.write_bytes(png_bytes())
    try:
        os.symlink(secret, root / "faces" / "real" / "link.png")              # symlinks are never followed
    except OSError:
        pass
    c = lab(devlab_dataset_dir=str(root))
    ds = c.dev.get(f"{D}/datasets").json()
    assert ds["available"] and ds["datasets"] == [{"name": "faces", "files": 3, "by_media": {"image": 3}, "labelled": 3, "real": 1, "fake": 2}]
    r = c.dev.post(f"{D}/jobs", json={"source": "dataset", "dataset": "faces", "media_types": ["image"]})
    assert r.status_code == 201
    d = c.dev.get(f"{D}/jobs/{r.json()['id']}").json()
    assert d["job"]["status"] == "completed" and len(d["items"]) == 3
    m = d["metrics"][0]
    assert m["available"] and m["true_positive"] == 2 and m["false_positive"] == 1 and m["accuracy"] == pytest.approx(2 / 3, abs=1e-3)
    assert (root / "faces" / "real" / "r1.png").is_file()                     # dataset files are never deleted
    assert c.dev.post(f"{D}/jobs", json={"source": "dataset", "dataset": "../etc"}).status_code == 404
    assert c.dev.post(f"{D}/jobs", json={"source": "dataset", "dataset": "missing"}).status_code == 404


def test_datasets_disabled_without_configuration(lab):
    c = lab()
    assert c.dev.get(f"{D}/datasets").json() == {"configured": False, "available": False, "datasets": []}
    r = c.dev.post(f"{D}/jobs", json={"source": "dataset", "dataset": "x"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "DATASETS_DISABLED"


def test_video_is_sampled_evenly_and_aggregated(lab, tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    path = tmp_path / "clip.avi"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
    if not w.isOpened():
        pytest.skip("OpenCV cannot write a test video here")
    for i in range(30):
        w.write(np.full((120, 160, 3), 100 + i, dtype=np.uint8))
    w.release()
    c = lab()
    jid = new_job(c.dev, video_frames=8, aggregation="top_quarter")
    r = add(c.dev, jid, "clip.avi", path.read_bytes(), "video/x-msvideo", "fake")
    assert r.status_code == 201, r.content
    it = run(c.dev, jid)["items"][0]
    assert it["status"] == "done" and it["frames_analyzed"] == 8 and it["score"] == pytest.approx(0.9) and it["prediction"] == "fake"
    full = c.dev.get(f"{D}/jobs/{jid}/items/{it['id']}").json()
    det = full["details"]
    assert det["aggregation"] == "top_quarter" and det["video"]["total_frames"] == 30 and len(det["frames"]) == 8
    assert det["frames"][0]["index"] == 0 and det["frames"][-1]["index"] == 29                  # first to last frame


# ---- pure parts -------------------------------------------------------------------------------------------------------------------

def _it(label, pred, score, status="done", media="image"):
    return {"label": label, "prediction": pred, "score": score, "status": status, "threshold": 0.5, "media_type": media, "detector": "vit"}


def test_metrics_on_a_known_confusion_matrix():
    items = [_it("fake", "fake", 0.9), _it("fake", "fake", 0.8), _it("fake", "real", 0.3), _it("real", "real", 0.1), _it("real", "fake", 0.6),
             _it("real", "real", 0.2), _it("", "fake", 0.9), _it("fake", "", None, status="unavailable"), _it("real", "", None, status="error")]
    m = metrics.evaluate(items)[0]
    assert (m["true_positive"], m["false_negative"], m["true_negative"], m["false_positive"]) == (2, 1, 2, 1)
    assert m["confusion_matrix"]["matrix"] == [[2, 1], [1, 2]]
    assert m["accuracy"] == pytest.approx(4 / 6, abs=1e-4) and m["precision"] == pytest.approx(2 / 3, abs=1e-4) and m["recall"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["f1"] == pytest.approx(2 / 3, abs=1e-3) and m["balanced_accuracy"] == pytest.approx(2 / 3, abs=1e-3)
    assert m["roc_auc"] == pytest.approx(8 / 9, abs=1e-4)                       # 8 of 9 (fake, real) pairs ranked correctly
    assert {e["reason"]: e["count"] for e in m["excluded"]} == {"unlabelled": 1, "unavailable": 1, "error": 1}


def test_metrics_refuse_to_invent_numbers():
    assert metrics.evaluate([_it("", "fake", 0.9)])[0]["available"] is False     # no labels: no accuracy
    one_class = metrics.evaluate([_it("fake", "fake", 0.9), _it("fake", "real", 0.2)])[0]
    assert one_class["available"] and one_class["specificity"] is None and one_class["roc_auc"] is None and one_class["balanced_accuracy"] is None
    nothing_fake = metrics.evaluate([_it("real", "real", 0.1)])[0]
    assert nothing_fake["precision"] is None and nothing_fake["recall"] is None
    assert metrics.roc_auc([(0.5, 1), (0.5, 0)]) == 0.5                         # ties count half


def test_lab_always_leaves_model_slots_for_live_sessions():
    g = InferenceGate(limit=3, shared=False)
    assert g.enter(reserve=2) and not g.enter(reserve=2)                       # the lab gets 1 of 3 slots at most
    assert g.enter() and g.enter() and not g.enter()                            # live traffic still gets the rest
    g.leave()
    assert g.enter()


def test_media_identification_by_content():
    from apps.devlab.media import identify, safe_filename, sniff_format
    assert sniff_format(png_bytes()[:16]) == "png" and sniff_format(wav_bytes(0.1)[:16]) == "wav"
    assert sniff_format(b"\x00\x00\x00\x18ftypisom" + b"\0" * 8) == "mp4" and sniff_format(b"\x00\x00\x00\x18ftypM4A " + b"\0" * 8) == "m4a"
    assert sniff_format(b"\x1a\x45\xdf\xa3" + b"\0" * 12) == "webm" and sniff_format(b"RIFF\0\0\0\0AVI LIST") == "avi" and sniff_format(b"hello world") is None
    assert identify("x.PNG", png_bytes()[:16]) == ("image", "png")
    assert safe_filename("../../etc/passwd") == "passwd" and safe_filename("C:\\Users\\a\\b.png") == "b.png" and safe_filename("") == "unnamed"
    assert Path(safe_filename("a" * 500)).name == "a" * 200
