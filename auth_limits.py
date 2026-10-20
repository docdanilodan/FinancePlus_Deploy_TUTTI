"""Bounded, temporary login throttling for the single-worker website.

Only digests and timestamps are retained. Passwords, usernames and IP addresses
are never logged or stored in the limiter. It uses Request.client supplied by
the ASGI server and deliberately does not parse forwarding headers itself.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import secrets
import threading
import time
from collections import deque

from fastapi import HTTPException


class LoginThrottled(Exception):
    def __init__(self, retry_after):
        self.retry_after = max(1, int(math.ceil(retry_after)))
        super().__init__("Troppi tentativi. Attendi e riprova.")


class LoginRateLimiter:
    def __init__(self, *, account_limit=10, ip_limit=60, window_seconds=300, max_buckets=4096, clock=time.monotonic):
        if account_limit < 1 or ip_limit < 1 or window_seconds <= 0 or max_buckets < 2:
            raise ValueError("Invalid login rate limits")
        self.account_limit = account_limit
        self.ip_limit = ip_limit
        self.window = window_seconds
        self.max_buckets = max_buckets
        self.clock = clock
        self._secret = secrets.token_bytes(32)
        self._buckets = {}
        self._lock = threading.Lock()
        self._next_cleanup = 0

    def _key(self, kind, value):
        return kind, hmac.new(self._secret, value.encode("utf-8"), hashlib.sha256).digest()

    def _prune(self, values, cutoff):
        while values and values[0] <= cutoff:
            values.popleft()

    def _cleanup(self, now):
        cutoff = now - self.window
        for key, values in list(self._buckets.items()):
            self._prune(values, cutoff)
            if not values:
                del self._buckets[key]
        self._next_cleanup = now + min(15, self.window)

    @property
    def bucket_count(self):
        with self._lock:
            return len(self._buckets)

    def check(self, client_host, username, mode="master"):
        try:
            host = str(ipaddress.ip_address(client_host))
        except (ValueError, TypeError):
            host = "unavailable"
        name = str(username or "").strip().casefold()[:128]
        channel = "site" if mode == "site" else "master"
        keys = ((self._key("ip", host), self.ip_limit), (self._key("account", channel + ":" + name), self.account_limit))
        now = self.clock()
        with self._lock:
            if now >= self._next_cleanup:
                self._cleanup(now)
            blocked_for = 0
            for key, limit in keys:
                values = self._buckets.get(key)
                if values:
                    self._prune(values, now - self.window)
                    if len(values) >= limit:
                        blocked_for = max(blocked_for, values[0] + self.window - now)
            if blocked_for > 0:
                # Rejected attempts do not extend the block or grow the state.
                raise LoginThrottled(blocked_for)
            missing = sum(key not in self._buckets for key, _ in keys)
            if len(self._buckets) + missing > self.max_buckets:
                self._cleanup(now)
                missing = sum(key not in self._buckets for key, _ in keys)
                if len(self._buckets) + missing > self.max_buckets:
                    # Never evict live counters: rotating names must not reset limits.
                    earliest = min(values[0] for values in self._buckets.values())
                    raise LoginThrottled(earliest + self.window - now)
            for key, _ in keys:
                self._buckets.setdefault(key, deque()).append(now)


_creation_lock = threading.Lock()


def throttle_login(request, username, mode="master"):
    limiter = getattr(request.app.state, "_financeplus_login_rate_limiter", None)
    if limiter is None:
        with _creation_lock:
            limiter = getattr(request.app.state, "_financeplus_login_rate_limiter", None)
            if limiter is None:
                limiter = LoginRateLimiter()
                request.app.state._financeplus_login_rate_limiter = limiter
    host = request.client.host if request.client else None
    try:
        limiter.check(host, username, mode)
    except LoginThrottled as exc:
        raise HTTPException(429, "Troppi tentativi di accesso. Attendi e riprova.", headers={"Retry-After": str(exc.retry_after)}) from None
