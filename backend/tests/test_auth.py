import pytest

from tests.conftest import client_for, ensure_user, make_settings, running_session  # noqa: F401
from apps.accounts.auth import issue_token, user_from_token


def login(c, username, password="correct-horse-9"):
    return c.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_login_returns_token_and_role(client):
    ensure_user("bob", "customer")
    ensure_user("ofc", "officer")
    r = login(client, "bob")
    body = r.json()
    assert r.status_code == 200 and body["user"]["role"] == "customer" and body["token"] and body["expires_at"]
    assert login(client, "OFC").json()["user"]["role"] == "officer"  # usernames are case-insensitive
    # the token works for /me
    c = client.__class__(body["token"])
    assert c.get("/api/v1/auth/me").json()["username"] == "bob"


def test_login_failures_are_uniform_and_rate_limited(make_client):
    c = make_client(login_max_attempts=3)
    ensure_user("bob")
    wrong_pw, no_user = login(c, "bob", "nope"), login(c, "ghost", "nope")
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["error"]["message"] == no_user.json()["error"]["message"]  # does not reveal which usernames exist
    login(c, "bob", "nope"), login(c, "bob", "nope")  # attempts 2 and 3 are still evaluated
    assert login(c, "bob", "nope").status_code == 429  # the 4th is refused
    assert login(c, "bob").status_code == 429  # even the right password, until the window passes
    assert login(c, "someone-else").status_code == 401  # throttle is per username


def test_inactive_user_cannot_login_or_use_token(client):
    u = ensure_user("bob")
    token = issue_token(u)[0]
    u.is_active = False
    u.save()
    assert login(client, "bob").status_code == 401
    assert user_from_token(token) is None


def test_register_creates_customer_only(client):
    c = client.__class__()
    r = c.post("/api/v1/auth/register", json={"username": "New.User", "password": "a-strong-pass-77"})
    assert r.status_code == 201 and r.json()["user"] == {"id": r.json()["user"]["id"], "username": "new.user", "role": "customer"}
    # extra fields such as role cannot be smuggled in
    r = c.post("/api/v1/auth/register", json={"username": "sneaky", "password": "a-strong-pass-77", "role": "officer"})
    assert r.json()["user"]["role"] == "customer"
    assert c.post("/api/v1/auth/register", json={"username": "NEW.user", "password": "a-strong-pass-77"}).json()["error"]["code"] == "USERNAME_TAKEN"
    for bad_pw in ("short", "password123", "12345678901"):
        assert c.post("/api/v1/auth/register", json={"username": "weak", "password": bad_pw}).json()["error"]["code"] == "WEAK_PASSWORD"
    assert c.post("/api/v1/auth/register", json={"username": "a!", "password": "a-strong-pass-77"}).status_code == 422


def test_register_can_be_disabled(make_client):
    c = make_client(allow_registration=False)
    r = c.__class__().post("/api/v1/auth/register", json={"username": "someone", "password": "a-strong-pass-77"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "REGISTRATION_DISABLED"


def test_tokens_expire_tamper_and_die_with_password_change(make_client):
    c = make_client(auth_token_ttl_minutes=0)  # everything expires immediately
    u = ensure_user("bob")
    assert user_from_token(issue_token(u)[0]) is None
    c = make_client()
    token = issue_token(u)[0]
    assert user_from_token(token).pk == u.pk
    assert user_from_token(token[:-2] + "xx") is None and user_from_token("not.a.token") is None
    u.set_password("another-pass-55")
    u.save()
    assert user_from_token(token) is None  # old tokens die when the password changes


def test_unauthenticated_and_bad_token_get_401(client):
    anon = client.__class__()
    r = anon.get("/api/v1/sessions")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED" and r["WWW-Authenticate"].startswith("Bearer")
    assert anon.post("/api/v1/sessions").status_code == 401
    bad = client.__class__("garbage")
    assert bad.get("/api/v1/sessions").status_code == 401
    assert anon.get("/health").status_code == 200  # probes stay public


def test_officer_is_read_only_and_cannot_run_verifications(client):
    sid = running_session(client)
    o = client.officer
    for method, url in [("post", "/api/v1/sessions"), ("post", f"/api/v1/sessions/{sid}/consent"), ("post", f"/api/v1/sessions/{sid}/start"),
                        ("post", f"/api/v1/sessions/{sid}/challenges"), ("post", f"/api/v1/sessions/{sid}/complete"), ("post", f"/api/v1/sessions/{sid}/cancel")]:
        r = getattr(o, method)(url, json={"granted": True}) if url.endswith("consent") else getattr(o, method)(url)
        assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN", url
    assert o.get(f"/api/v1/sessions/{sid}").status_code == 200 and o.get(f"/api/v1/sessions/{sid}/challenges").status_code == 200


def test_customer_cannot_read_risk_or_evidence(client):
    sid = running_session(client)
    for url in (f"/api/v1/sessions/{sid}/analysis", f"/api/v1/sessions/{sid}/evidence", f"/api/v1/sessions/{sid}/evidence/export", "/api/v1/models/status"):
        r = client.get(url)
        assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN", url
    assert client.post(f"/api/v1/sessions/{sid}/evidence/verify").status_code == 403
    assert client.post(f"/api/v1/sessions/{sid}/analysis/session").status_code == 403
    body = client.get(f"/api/v1/sessions/{sid}").json()
    assert "final_risk_level" not in body and "summary" not in body and "customer" not in body


def test_customers_are_isolated_from_each_other(client):
    mine = running_session(client)
    other = client_for(ensure_user("mallory", "customer"))
    # another customer's session looks like it does not exist, for every action
    for method, url in [("get", f"/api/v1/sessions/{mine}"), ("get", f"/api/v1/sessions/{mine}/challenges"), ("post", f"/api/v1/sessions/{mine}/start"),
                        ("post", f"/api/v1/sessions/{mine}/challenges"), ("post", f"/api/v1/sessions/{mine}/cancel"), ("post", f"/api/v1/sessions/{mine}/complete")]:
        r = getattr(other, method)(url)
        assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND", url
    assert other.post(f"/api/v1/sessions/{mine}/consent", json={"granted": False}).status_code == 404
    from tests.conftest import wav_bytes
    assert other.post(f"/api/v1/sessions/{mine}/analysis/audio", files={"file": ("a.wav", wav_bytes(), "audio/wav")}).status_code == 404
    assert client.get(f"/api/v1/sessions/{mine}").json()["status"] == "running"  # untouched


def test_lists_are_scoped_by_role(client):
    mine = [client.post("/api/v1/sessions").json()["id"] for _ in range(2)]
    other = client_for(ensure_user("mallory", "customer"))
    theirs = other.post("/api/v1/sessions").json()["id"]
    assert {x["id"] for x in client.get("/api/v1/sessions").json()["items"]} == set(mine)
    assert client.get("/api/v1/sessions").json()["total"] == 2
    items = client.officer.get("/api/v1/sessions").json()["items"]
    assert {x["id"] for x in items} == set(mine) | {theirs}
    assert {x["customer"] for x in items} == {"alice", "mallory"}  # officers see whose session it is
    assert all("final_risk_level" in x for x in items)


def test_upload_response_does_not_leak_risk(client):
    from tests.conftest import wav_bytes
    sid = running_session(client)
    r = client.post(f"/api/v1/sessions/{sid}/analysis/audio", files={"file": ("a.wav", wav_bytes(), "audio/wav")}).json()
    assert r == {"received": True, "detectors": [{"name": "audio", "status": "ok"}]}
    assert "recommendation" not in r and "signals" not in r and "score" not in str(r)


def test_create_officer_command(db):
    from django.core.management import call_command
    from apps.accounts.models import User
    call_command("create_officer", "chief", "--password", "a-strong-pass-77")
    u = User.objects.get(username="chief")
    assert u.role == "officer" and u.check_password("a-strong-pass-77")
    with pytest.raises(Exception):
        call_command("create_officer", "chief2", "--password", "123")  # weak password rejected


def test_demo_users_command_is_development_only(db, settings):
    from django.core.management import call_command
    from apps.accounts.models import User
    settings.DEBUG = False
    with pytest.raises(Exception):
        call_command("create_demo_users")
    assert not User.objects.filter(username="officer").exists()
    settings.DEBUG = True
    call_command("create_demo_users")
    assert User.objects.get(username="officer").role == "officer" and User.objects.get(username="customer").role == "customer"
