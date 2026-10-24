from tests.conftest import answer_challenge, running_session

S = "/api/v1/sessions"


def test_requires_running(client):
    sid = client.post(S).json()["id"]
    assert client.post(f"{S}/{sid}/challenges").status_code == 403


def test_issue_and_result_flow(client):
    sid = running_session(client)
    r = client.post(f"{S}/{sid}/challenges")
    assert r.status_code == 201
    c = r.json()
    assert c["status"] == "issued" and c["challenge_text"]
    assert "result" not in c and "reason" not in c   # the customer never sees how a check is judged
    url = f"{S}/{sid}/challenges/{c['id']}/result"
    a = client.post(url, json={"measured": {}}).json()
    assert a["status"] == "answered" and "result" not in a
    seen = next(x for x in client.officer.get(f"{S}/{sid}/challenges").json() if x["id"] == c["id"])
    assert seen["result"] == "unavailable"  # nothing measured: not claimed as pass or fail
    assert client.post(url, json={"measured": {}}).json()["error"]["code"] == "CHALLENGE_ALREADY_ANSWERED"  # replay rejected
    assert len(client.get(f"{S}/{sid}/challenges").json()) == 1


def test_customer_view_never_contains_results(client):
    sid = running_session(client)
    answer_challenge(client, sid, "blink", {"blink_count": 2})
    for row in client.get(f"{S}/{sid}/challenges").json():
        assert not ({"result", "reason", "verification", "confidence"} & set(row))


def test_challenges_continue_for_the_whole_session(client):
    """No fixed number: each finished challenge is followed by another, never the same type twice in a row."""
    sid = running_session(client)
    kinds = []
    for _ in range(8):
        c = client.post(f"{S}/{sid}/challenges").json()
        kinds.append(c["challenge_type"])
        assert client.post(f"{S}/{sid}/challenges/{c['id']}/result", json={"measured": {}}).status_code == 200
    assert len(client.get(f"{S}/{sid}/challenges").json()) == 8
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
    assert "eye_scan" not in kinds   # needs an enrolled reference iris


def test_asking_again_returns_the_open_challenge(client):
    sid = running_session(client)
    a = client.post(f"{S}/{sid}/challenges")
    b = client.post(f"{S}/{sid}/challenges")
    assert a.status_code == 201 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    assert len(client.get(f"{S}/{sid}/challenges").json()) == 1


def test_phrase_measurement(client):
    sid = running_session(client)
    ch = client.officer.post(f"{S}/{sid}/challenges/issue", json={"type": "phrase"}).json()
    phrase = ch["challenge_text"].removeprefix("Say aloud: ")
    r = client.post(f"{S}/{sid}/challenges/{ch['id']}/result", json={"measured": {"spoken_text": phrase.upper()}})
    assert r.status_code == 200
    seen = next(x for x in client.officer.get(f"{S}/{sid}/challenges").json() if x["id"] == ch["id"])
    assert seen["result"] == "passed"


def test_head_turn_direction(client):
    sid = running_session(client)
    assert answer_challenge(client, sid, "head_left", {"head_yaw_deg": -30})["result"] == "passed"
    assert answer_challenge(client, sid, "head_left", {"head_yaw_deg": 30})["result"] == "failed"
    assert answer_challenge(client, sid, "head_right", {"head_yaw_deg": 5})["result"] == "failed"
    assert answer_challenge(client, sid, "blink", {"blink_count": 1})["result"] == "failed"


def test_eye_scan_cannot_be_answered_with_a_number(client):
    sid = running_session(client)
    ch = client.officer.post(f"{S}/{sid}/challenges/issue", json={"type": "eye_scan"}).json()
    assert ch["challenge_type"] == "eye_scan"
    r = client.post(f"{S}/{sid}/challenges/{ch['id']}/result", json={"measured": {"blink_count": 2}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "USE_EYE_SCAN_ENDPOINT"


def test_expiry_and_ownership(make_client):
    c = make_client(challenge_ttl_seconds=0)
    sid = running_session(c)
    ch = c.post(f"{S}/{sid}/challenges").json()
    assert c.post(f"{S}/{sid}/challenges/{ch['id']}/result", json={"measured": {}}).status_code == 410
    other = running_session(c)
    assert c.post(f"{S}/{other}/challenges/{ch['id']}/result", json={"measured": {}}).json()["error"]["code"] == "CHALLENGE_NOT_FOUND"


def test_expired_challenge_is_replaced_by_a_new_one(make_client):
    c = make_client(challenge_ttl_seconds=0)
    sid = running_session(c)
    first = c.post(f"{S}/{sid}/challenges").json()
    second = c.post(f"{S}/{sid}/challenges").json()
    assert first["id"] != second["id"]
    rows = c.officer.get(f"{S}/{sid}/challenges").json()
    assert [r["status"] for r in rows][0] == "expired"


def test_phrase_words_are_india_related_and_distinct():
    from apps.challenges import services as cs
    seen = set()
    for _ in range(300):
        c = cs.issue("00000000-0000-0000-0000-000000000000", 60, kind="phrase")
        words = c.challenge_text.removeprefix("Say aloud: ").split()
        assert len(words) == 3 and len(set(words)) == 3 and set(words) <= set(cs.WORDS)
        seen.update(words)
    assert len(seen) > 10 and {"Delhi", "Diwali"} <= set(cs.WORDS)


def test_server_cross_check_overrules_a_faked_head_turn():
    from apps.challenges import services as cs
    from apps.challenges.models import Challenge
    c = Challenge(challenge_type="head_left", challenge_text="", sequence=1)
    faked = {"head_yaw_deg": -40}
    still = {"n": 8, "turn_left_deg": 1.0, "turn_right_deg": 0.5, "ear_dips": 0, "mar_range": 0.0}
    turned = {"n": 8, "turn_left_deg": 25.0, "turn_right_deg": 0.0, "ear_dips": 0, "mar_range": 0.0}
    r, d = cs.evaluate(c, faked, still)
    assert r == "failed" and d["verification"] == "mismatch"
    r, d = cs.evaluate(c, {}, turned)
    assert r == "passed" and d["verification"] == "server_confirmed"   # the server saw it even though the browser reported nothing
    r, d = cs.evaluate(c, faked, None)
    assert r == "passed" and d["verification"] == "client_only"


def test_officer_choice_replaces_the_open_challenge(client):
    """'Send to customer' must win: the generated challenge that was still open is closed (not counted as missed)."""
    sid = running_session(client)
    generated = client.post(f"{S}/{sid}/challenges").json()
    chosen = client.officer.post(f"{S}/{sid}/challenges/issue", json={"type": "phrase"}).json()
    assert chosen["challenge_type"] == "phrase"
    rows = {x["id"]: x for x in client.officer.get(f"{S}/{sid}/challenges").json()}
    assert rows[generated["id"]]["status"] == "expired" and rows[generated["id"]]["approval_status"] == "regenerated"
    again = client.post(f"{S}/{sid}/challenges")  # the customer's page asks for "the open one": it gets the officer's choice
    assert again.status_code == 200 and again.json()["id"] == chosen["id"]


def _phrase_upload(client, sid, cid, spoken=None, silent=False):
    from tests.conftest import wav_bytes
    return client.post(f"{S}/{sid}/challenges/{cid}/phrase", files={"file": ("p.wav", wav_bytes(1.0, silent=silent), "audio/wav")},
                       fields={"spoken_text": spoken} if spoken else None)


def test_phrase_is_judged_on_the_server_transcript(client, monkeypatch):
    from apps.challenges import speech
    sid = running_session(client)
    ch = client.officer.post(f"{S}/{sid}/challenges/issue", json={"type": "phrase"}).json()
    words = ch["challenge_text"].removeprefix("Say aloud: ")
    monkeypatch.setattr(speech, "transcribe", lambda wave, sr: (words.lower() + ".", "ok"))
    r = _phrase_upload(client, sid, ch["id"], spoken="something else entirely")  # the browser's text is not trusted over the server's
    assert r.status_code == 200 and "result" not in r.json()
    seen = next(x for x in client.officer.get(f"{S}/{sid}/challenges").json() if x["id"] == ch["id"])
    assert seen["result"] == "passed" and seen["verification"] == "server_confirmed"


def test_phrase_without_speech_model_falls_back_to_the_browser(client, monkeypatch):
    from apps.challenges import speech
    sid = running_session(client)
    ch = client.officer.post(f"{S}/{sid}/challenges/issue", json={"type": "phrase"}).json()
    monkeypatch.setattr(speech, "transcribe", lambda wave, sr: (None, "MODEL_NOT_DOWNLOADED"))
    assert _phrase_upload(client, sid, ch["id"]).status_code == 200
    seen = next(x for x in client.officer.get(f"{S}/{sid}/challenges").json() if x["id"] == ch["id"])
    assert seen["result"] == "unavailable" and "download_models.py --speech" in seen["reason"]


def test_phrase_matching_tolerates_spelling_variants():
    from apps.challenges.services import _phrase_match
    assert _phrase_match("Holi Lassi Bollywood", "holy lassie bolly wood")[0] == 3
    assert _phrase_match("Delhi Mango Goa", "tea cup window")[0] == 0
