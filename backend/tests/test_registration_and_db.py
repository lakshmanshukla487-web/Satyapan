"""Sign-up must never answer with a bare HTTP 500: it succeeds, or says exactly what is wrong."""
import logging

import pytest
from django.core.management import call_command
from django.db import OperationalError

from tests.conftest import Client, make_settings  # noqa: F401

REGISTER = "/api/v1/auth/register"
BODY = {"username": "New.Person", "password": "a-strong-pass-77"}


def _anon():
    return Client()


def test_register_then_use_the_token(make_client):
    make_client()
    c = _anon()
    r = c.post(REGISTER, json=BODY)
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["user"]["username"] == "new.person" and body["user"]["role"] == "customer" and body["token"]
    me = Client(body["token"]).get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "new.person"


def test_register_login_roundtrip(make_client):
    make_client()
    c = _anon()
    assert c.post(REGISTER, json=BODY).status_code == 201
    assert c.post("/api/v1/auth/login", json={"username": "NEW.person", "password": BODY["password"]}).status_code == 200


@pytest.mark.parametrize("payload", [{}, {"username": "x"}, {"password": "a-strong-pass-77"}, {"username": 5, "password": 6}, {"username": "ok.user", "password": None}])
def test_malformed_register_bodies_are_422_never_500(make_client, payload):
    make_client()
    assert _anon().post(REGISTER, json=payload).status_code == 422


def test_register_with_no_body_or_wrong_content_type(make_client):
    make_client()
    r = _anon().post(REGISTER)
    assert r.status_code in (415, 422)


def test_database_not_ready_is_a_clear_503_with_a_log_hint(make_client, monkeypatch, caplog):
    """The classic cause of the original 500: tables missing / out of date. The client gets an actionable 503; the log says what to run."""
    from django.contrib.auth import get_user_model
    make_client()

    def boom(*a, **k):
        raise OperationalError("no such table: accounts_user")
    monkeypatch.setattr(get_user_model().objects.__class__, "create_user", boom)
    with caplog.at_level(logging.ERROR, logger="satyapan"):
        r = _anon().post(REGISTER, json=BODY)
    assert r.status_code == 503 and r.json()["error"]["code"] == "DATABASE_NOT_READY"
    assert "setup_db" in r.json()["error"]["message"] or "setup" in r.json()["error"]["message"].lower()
    assert any("setup_db" in rec.getMessage() for rec in caplog.records)         # the server log tells the operator the fix
    assert "accounts_user" not in r.content.decode()                              # internals are not leaked to the browser


def test_unexpected_error_is_json_500_without_internals(make_client, monkeypatch, caplog):
    from django.contrib.auth import get_user_model
    make_client()

    def boom(*a, **k):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(get_user_model().objects.__class__, "create_user", boom)
    with caplog.at_level(logging.ERROR, logger="satyapan"):
        r = _anon().post(REGISTER, json=BODY)
    body = r.json()
    assert r.status_code == 500 and body["error"]["code"] == "INTERNAL_ERROR" and body["error"]["request_id"]
    assert "secret internal detail" not in r.content.decode()
    assert any("RuntimeError" in rec.getMessage() for rec in caplog.records)      # but the traceback is in the server log


def test_duplicate_username_is_409(make_client):
    make_client()
    c = _anon()
    assert c.post(REGISTER, json=BODY).status_code == 201
    r = c.post(REGISTER, json={**BODY, "username": "new.PERSON"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "USERNAME_TAKEN"


def test_setup_db_check_passes_on_a_correct_schema(db):
    call_command("setup_db", "--check")


def test_setup_db_check_reports_a_missing_table(db):
    from django.core.management.base import CommandError
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute("DROP TABLE biometrics_observation")
    with pytest.raises(CommandError):
        call_command("setup_db", "--check")


def test_schema_problems_names_the_missing_pieces(db):
    from apps.core.management.commands.setup_db import schema_problems
    assert schema_problems() == []
