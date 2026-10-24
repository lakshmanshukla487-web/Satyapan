"""Rate limiting: per-account buckets (customers behind one LAN address do not share), per-address limits for anonymous traffic,
an address ceiling, Retry-After, separate media bucket, and throttled requests that never reach the view."""
from apps.core.middleware import _MEDIA_PATH
from apps.core.runtime import RateLimiter
from tests.conftest import Client, client_for, ensure_user, png_bytes

S = "/api/v1/sessions"


def _customers(n):
    return [client_for(ensure_user(f"lan{i}", "customer")) for i in range(n)]


def test_several_customers_behind_one_address_have_their_own_buckets(make_client):
    make_client(rate_limit_user_per_minute=5, rate_limit_per_minute=5)
    a, b, c = _customers(3)  # the test client uses one REMOTE_ADDR for everybody, like a shared LAN / NAT / the Vite proxy
    for cl in (a, b, c):
        for _ in range(5):
            assert cl.get("/api/v1/auth/me").status_code == 200
    r = a.get("/api/v1/auth/me")
    assert r.status_code == 429
    body = r.json()["error"]
    assert body["code"] == "RATE_LIMITED" and body["scope"] == "user" and body["request_id"] and body["retry_after"] >= 1
    assert int(r["Retry-After"]) == body["retry_after"] and r["X-Request-ID"] == body["request_id"]


def test_media_uploads_use_a_separate_bucket(make_client):
    c = make_client(rate_limit_user_per_minute=3, rate_limit_media_per_minute=50)
    sid = c.post(S).json()["id"]
    c.post(f"{S}/{sid}/consent", json={"granted": True}), c.post(f"{S}/{sid}/start")  # 3 API calls: the API bucket is full now
    assert c.get("/api/v1/auth/me").status_code == 429
    for _ in range(10):  # frames still go through: a busy live check does not lock the customer out of the API, and vice versa
        assert c.post(f"{S}/{sid}/analysis/frame", files={"file": ("f.png", png_bytes(), "image/png")}).status_code == 200


def test_media_path_classification():
    for p in ("/api/v1/sessions/x/analysis/frame", "/api/v1/sessions/x/analysis/audio", "/api/v1/sessions/x/analysis/avsync",
              "/api/v1/sessions/x/challenges/y/eye-scan", "/api/v1/devlab/jobs/j/items"):
        assert _MEDIA_PATH.search(p), p
    for p in ("/api/v1/sessions", "/api/v1/sessions/x/challenges", "/api/v1/rtc/config", "/api/v1/sessions/x/analysis", "/api/v1/devlab/jobs/j/items/i"):
        assert not _MEDIA_PATH.search(p), p


def test_anonymous_requests_are_limited_per_address(make_client):
    make_client(rate_limit_per_minute=3)
    anon = Client()
    assert [anon.get("/health").status_code for _ in range(4)] == [200, 200, 200, 429]
    forged = Client("not-a-valid-token")  # an invalid token does not buy a fresh bucket: it counts as anonymous
    r = forged.get("/health")
    assert r.status_code == 429 and r.json()["error"]["scope"] == "anonymous"


def test_address_ceiling_still_stops_many_accounts_from_one_address(make_client):
    make_client(rate_limit_ip_ceiling_per_minute=6)
    clients = _customers(4)
    codes = [cl.get("/api/v1/auth/me").status_code for cl in clients for _ in range(2)]
    assert codes.count(200) == 6 and codes[-1] == 429


def test_throttled_request_never_creates_anything(make_client):
    from apps.verification.models import VerificationSession
    c = make_client(rate_limit_user_per_minute=2)
    assert c.post(S).status_code == 201
    assert c.post(S).status_code == 201
    r = c.post(S)
    assert r.status_code == 429
    assert VerificationSession.objects.filter(owner__username="alice").count() == 2  # the refused request did not reach the view


def test_login_throttle_is_still_active_and_says_when_to_retry(make_client):
    make_client(login_max_attempts=2)
    ensure_user("bob")
    anon = Client()
    for _ in range(2):
        assert anon.post("/api/v1/auth/login", json={"username": "bob", "password": "nope"}).status_code == 401
    r = anon.post("/api/v1/auth/login", json={"username": "bob", "password": "correct-horse-9"})
    assert r.status_code == 429 and int(r["Retry-After"]) >= 1 and r.json()["error"]["retry_after"] >= 1


def test_in_memory_limiter_reports_retry_after_and_prunes():
    rl = RateLimiter()
    assert rl.hit("k", 2, 60) == (True, 0) and rl.hit("k", 2, 60) == (True, 0)
    ok, retry = rl.hit("k", 2, 60)
    assert not ok and 1 <= retry <= 60
    assert rl.allow("other", 1, 60) and not rl.allow("other", 1, 60)


def test_a_normal_verification_flow_stays_far_below_the_default_limits(make_client):
    """A session's worth of customer and officer traffic with the PRODUCT defaults (not the test overrides): no 429."""
    from satyapan.conf import AppSettings
    d = AppSettings()
    c = make_client(rate_limit_per_minute=d.rate_limit_per_minute, rate_limit_user_per_minute=d.rate_limit_user_per_minute,
                    rate_limit_media_per_minute=d.rate_limit_media_per_minute, rate_limit_ip_ceiling_per_minute=d.rate_limit_ip_ceiling_per_minute)
    sid = c.post(S).json()["id"]
    codes = [c.post(f"{S}/{sid}/consent", json={"granted": True}).status_code, c.post(f"{S}/{sid}/start").status_code]
    for i in range(40):  # one minute of a live check: frames every 3 s plus a dense series during challenges
        codes.append(c.post(f"{S}/{sid}/analysis/frame", files={"file": ("f.png", png_bytes(), "image/png")}).status_code)
        if i % 4 == 0:
            codes.append(c.get(f"{S}/{sid}/challenges/current").status_code)
            codes.append(c.officer.get("/api/v1/officer/dashboard").status_code)
            codes.append(c.officer.get(f"{S}/{sid}/challenges").status_code)
    assert 429 not in codes and set(codes) <= {200, 201}
