"""Targeted access-limit checks; all identities and authentication are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from auth_limits import LoginRateLimiter, LoginThrottled, throttle_login
from test_portal_integration import hidden, portal


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_account_limit_normalizes_name_and_expires_without_extending_rejections():
    clock = Clock()
    limiter = LoginRateLimiter(account_limit=2, ip_limit=20, window_seconds=10, clock=clock)
    limiter.check("192.0.2.1", "Person@example.invalid")
    limiter.check("192.0.2.2", " " * 200 + "PERSON@EXAMPLE.INVALID  ")
    clock.now += 4
    with pytest.raises(LoginThrottled) as blocked:
        limiter.check("192.0.2.3", "person@example.invalid", mode="arbitrary-master-mode")
    assert blocked.value.retry_after == 6
    clock.now += 5
    with pytest.raises(LoginThrottled) as blocked:
        limiter.check("192.0.2.4", "person@example.invalid")
    assert blocked.value.retry_after == 1
    clock.now += 1
    limiter.check("192.0.2.5", "person@example.invalid")


def test_ip_limit_ignores_forwarded_headers_and_does_not_store_raw_identifiers():
    app = FastAPI()
    limiter = LoginRateLimiter(account_limit=10, ip_limit=2, window_seconds=60, clock=lambda: 100)
    app.state._financeplus_login_rate_limiter = limiter
    for number in range(3):
        request = Request({
            "type": "http", "app": app, "method": "POST", "path": "/login",
            "client": ("192.0.2.91", 12000),
            "headers": [(b"x-forwarded-for", f"203.0.113.{number}".encode())],
        })
        if number < 2:
            throttle_login(request, f"person{number}@example.invalid")
        else:
            with pytest.raises(HTTPException) as blocked:
                throttle_login(request, f"person{number}@example.invalid")
            assert blocked.value.status_code == 429
            assert blocked.value.headers == {"Retry-After": "60"}
    state = repr(limiter._buckets)
    assert "192.0.2.91" not in state
    assert "example.invalid" not in state


def test_capacity_is_bounded_without_eviction_and_recovers_after_window():
    clock = Clock()
    limiter = LoginRateLimiter(account_limit=2, ip_limit=2, window_seconds=10, max_buckets=4, clock=clock)
    limiter.check("192.0.2.1", "first@example.invalid")
    limiter.check("192.0.2.2", "second@example.invalid")
    assert limiter.bucket_count == 4
    for number in range(100):
        with pytest.raises(LoginThrottled):
            limiter.check(f"203.0.113.{number}", f"new-{number}@example.invalid")
    assert limiter.bucket_count == 4
    limiter.check("192.0.2.1", "first@example.invalid")
    with pytest.raises(LoginThrottled):
        limiter.check("192.0.2.1", "first@example.invalid")
    clock.now += 10
    limiter.check("192.0.2.3", "new@example.invalid")
    assert limiter.bucket_count == 2


def test_parallel_requests_cannot_race_past_account_limit():
    limiter = LoginRateLimiter(account_limit=4, ip_limit=60, clock=lambda: 100)

    def attempt(number):
        try:
            limiter.check(f"192.0.2.{number + 1}", "same@example.invalid")
        except LoginThrottled:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(attempt, range(20)))
    assert sum(outcomes) == 4
    assert limiter.bucket_count == 5


@pytest.mark.parametrize("mode", ["site", "master"])
def test_login_hook_rejects_before_password_hash_or_gateway(portal, monkeypatch, mode):
    portal.module.app.state._financeplus_login_rate_limiter = LoginRateLimiter(
        account_limit=2, ip_limit=20, window_seconds=5, clock=lambda: 100
    )
    password_checks = []

    def reject_password(password, password_hash):
        password_checks.append(True)
        return False

    monkeypatch.setattr(portal.module, "pwcheck", reject_password)
    email = "local-admin@example.invalid" if mode == "site" else "admin@example.invalid"
    initial = portal.client.get("/login", params={"mode": mode})
    data = {**hidden(initial), "email": email, "password": "synthetic-incorrect-password", "mode": mode}
    for _ in range(2):
        assert portal.client.post("/login", data=data).status_code == 303
    response = portal.client.post("/login", data=data)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "5"
    assert email not in response.text
    assert data["password"] not in response.text
    gateway_logins = [call for call in portal.fake.calls if call["path"] == "/v1/accounts/session"]
    assert len(password_checks) == (2 if mode == "site" else 0)
    assert len(gateway_logins) == (2 if mode == "master" else 0)


def test_invalid_csrf_does_not_consume_login_capacity_or_attempt_authentication(portal):
    limiter = LoginRateLimiter(account_limit=1, ip_limit=1)
    portal.module.app.state._financeplus_login_rate_limiter = limiter
    response = portal.client.post("/login", data={
        "email": "admin@example.invalid", "password": "synthetic-incorrect-password", "csrf_token": "invalid",
    })
    assert response.status_code == 403
    assert limiter.bucket_count == 0
    assert not portal.fake.calls
