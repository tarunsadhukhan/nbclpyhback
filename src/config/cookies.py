"""Single source of truth for auth-cookie attributes.

The domain used to be hardcoded to ".vowerp.co.in" in five separate places
(authorization/utils.py, authorization/auth.py x2, authorization/routers.py,
common/portal/menu.py). A browser silently DISCARDS a cookie whose Domain
attribute does not match the site it came from, so deploying under any other
domain with ENV=production produced a login that appeared to succeed - the
API returned 200 with a token - while every subsequent request came back
401/403 because no cookie was ever stored. That failure mode reads like "wrong
password" or "session expired" and is painful to trace back to a cookie
attribute, which is why this now lives in exactly one function.

Set COOKIE_DOMAIN per deployment, e.g. ".punrasargroup.com". Leaving it unset
yields host-only cookies, which is the correct default - you only need an
explicit Domain when cookies must be shared ACROSS subdomains.
"""

from __future__ import annotations

import os
from typing import Any, Dict


def cookie_settings() -> Dict[str, Any]:
    """Return the domain/secure/samesite triple for auth cookies.

    `secure` and `samesite=None` are tied to ENV=production because SameSite=None
    is only honoured on HTTPS; sending it over plain HTTP makes browsers drop the
    cookie. Keep ENV=development until the deployment actually serves HTTPS.
    """
    is_prod = os.getenv("ENV", "development") == "production"

    # Empty or whitespace-only is treated as unset, so a blank line in an .env
    # file cannot produce Domain="" and break every cookie.
    domain = (os.getenv("COOKIE_DOMAIN") or "").strip() or None

    return {
        "domain": domain if is_prod else None,
        "secure": is_prod,
        "samesite": "None" if is_prod else "Lax",
    }


if __name__ == "__main__":
    # Smallest runnable check: the bug was a hardcoded domain leaking into a
    # deployment it did not belong to, so pin the behaviour that prevents it.
    _saved = {k: os.environ.get(k) for k in ("ENV", "COOKIE_DOMAIN")}

    def _set(**kw):
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    _set(ENV="development", COOKIE_DOMAIN=None)
    s = cookie_settings()
    assert s == {"domain": None, "secure": False, "samesite": "Lax"}, s

    # dev must never emit a Domain, even if one is configured
    _set(ENV="development", COOKIE_DOMAIN=".punrasargroup.com")
    assert cookie_settings()["domain"] is None, "dev must not set a cookie domain"

    # production honours the configured domain
    _set(ENV="production", COOKIE_DOMAIN=".punrasargroup.com")
    s = cookie_settings()
    assert s == {"domain": ".punrasargroup.com", "secure": True, "samesite": "None"}, s

    # production without COOKIE_DOMAIN falls back to host-only, NOT a stale default
    _set(ENV="production", COOKIE_DOMAIN=None)
    assert cookie_settings()["domain"] is None, "must not invent a domain"

    # blank/whitespace is treated as unset
    _set(ENV="production", COOKIE_DOMAIN="   ")
    assert cookie_settings()["domain"] is None, "blank COOKIE_DOMAIN must be None"

    for k, v in _saved.items():
        _set(**{k: v})
    print("cookie_settings: all checks passed")
