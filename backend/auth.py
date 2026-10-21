"""
Access keys ("sign-in") and a daily limit, so a link that gets shared can't run up your AI bill.

ACCESS_KEY (in .env) turns the lock on. It can hold one key or several, separated by commas.
Give each person their own key and you can see (and cut off) people one by one:

    ACCESS_KEY=ravi=k7Hq2xPz,priya=Vb83nLmQ,guest=T5wYc9Ae
    ACCESS_KEY=justonesharedkey                      # the old single-key style still works

  * "name=key" gives that person a name (letters, digits, - _ . only). The name is shown to them
    on the page and is what their daily limit is counted against.
  * A key without a name is counted under a short code made from the key.
  * Leave ACCESS_KEY empty to turn the lock off (fine on your own computer, not on a public link).

DAILY_JOB_LIMIT (in .env) caps how many transcription / text jobs ONE person can start in 24
hours (0 = no cap). With the lock on, "one person" = one key; with it off, one IP address.
A person who types a wrong key 10 times in 10 minutes is paused for the rest of that window.

This is still a shared-secret scheme, not full accounts: fine for sharing with friends, a class or
a small team. Replace it with real sign-in (OAuth etc.) before handling anything sensitive.
"""
import hashlib
import hmac
import re
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

from config import settings

_NAMED = re.compile(r"^([A-Za-z0-9_.-]{1,30})=(.+)$")
_MAX_FAILURES = 10
_WINDOW_SECONDS = 600
_failures: dict[str, deque] = defaultdict(deque)


def parse_keys() -> list[tuple[str, str]]:
    """[(name, key), ...] from ACCESS_KEY. Empty list = the lock is off."""
    out = []
    for part in (settings.access_key or "").split(","):
        part = part.strip()
        if not part:
            continue
        m = _NAMED.match(part)
        if m:
            out.append((m.group(1), m.group(2).strip()))
        else:
            out.append(("key-" + hashlib.sha256(part.encode()).hexdigest()[:6], part))
    return out


def auth_enabled() -> bool:
    return bool(parse_keys())


def client_ip(request: Request) -> str:
    """The visitor's address. Behind Render / ngrok / Colab every request comes from the proxy, so the
    real address is in X-Forwarded-For (TRUST_PROXY=true, the default; set false if exposed directly)."""
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def owner_of(request: Request) -> str:
    """Who a job counts against: the signed-in name, else the IP address."""
    user = getattr(request.state, "user", None)
    return f"user:{user}" if user else f"ip:{client_ip(request)}"


def _locked_out(ip: str) -> bool:
    q = _failures[ip]
    cutoff = time.time() - _WINDOW_SECONDS
    while q and q[0] < cutoff:
        q.popleft()
    return len(q) >= _MAX_FAILURES


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)):
    keys = parse_keys()
    request.state.user = None
    if not keys:
        return  # lock is off — see the docstring

    ip = client_ip(request)
    if x_api_key and _locked_out(ip):
        raise HTTPException(429, "Too many wrong keys. Please wait 10 minutes and try again.")

    for name, key in keys:
        if x_api_key and hmac.compare_digest(x_api_key.encode(), key.encode()):
            request.state.user = name
            return

    if x_api_key:  # a missing header is just a first visit; only wrong keys count as attempts
        _failures[ip].append(time.time())
    raise HTTPException(401, "Missing or incorrect API key.")
