"""
Authentication: simple bearer API keys, not full SSO.

ConsultCastAI is a solo-founder / small-cohort product (AI Curator LLC), not an
enterprise deployment behind a customer's IdP, so full SSO is over-engineered
for where this is right now. Instead:

- Each rep (consultant) gets an issued API key, set server-side via the
  CONSULTCASTAI_API_KEYS env var: a comma-separated list of "key:rep_id" pairs,
  e.g. "sk_abc123:scott,sk_def456:jane".
- The Authorization: Bearer <key> header is matched against that list.
- If the env var is unset, auth FAILS CLOSED (500), never admits everyone.
- A local-dev bypass exists for zero-setup local testing. It is DELIBERATELY
  independent of which storage backend is active (CONSULTCASTAI_DEV_AUTH_BYPASS,
  see _dev_bypass_enabled below): storage backend and "should auth be
  enforced" are separate questions. A deploy can use local-JSON storage
  (e.g. on a Render disk, no cloud DB needed) while still requiring real
  API keys, or use a real database while still bypassing auth for local
  testing against it. Defaults to matching local-store mode when unset, so
  the zero-setup local dev experience is unchanged unless you opt in.

This is intentionally swappable: when ConsultCastAI has real customers with
their own IdPs, replace verify_user's body with Firebase/Auth0/Okta token
verification and nothing else in the app needs to change, every route
depends on AuthUser, not on how it was produced.
"""

import os
from dataclasses import dataclass

from fastapi import Header, HTTPException

import store

_API_KEYS_ENV = "CONSULTCASTAI_API_KEYS"     # "key:rep_id,key:rep_id"
_ADMIN_REPS_ENV = "CONSULTCASTAI_ADMIN_REPS"  # comma-separated rep_ids
_DEV_AUTH_BYPASS_ENV = "CONSULTCASTAI_DEV_AUTH_BYPASS"  # "1"/"0", overrides the storage-based default


@dataclass
class AuthUser:
    rep_id: str
    email: str
    is_admin: bool


def _key_map() -> dict[str, str]:
    raw = os.environ.get(_API_KEYS_ENV, "")
    pairs = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        key, rep_id = entry.split(":", 1)
        pairs[key.strip()] = rep_id.strip()
    return pairs


def _admin_reps() -> set[str]:
    raw = os.environ.get(_ADMIN_REPS_ENV, "")
    return {r.strip() for r in raw.split(",") if r.strip()}


def _dev_bypass_enabled() -> bool:
    """Explicit CONSULTCASTAI_DEV_AUTH_BYPASS wins if set ("1" or "0").
    Otherwise falls back to matching local-store mode, preserving the
    original zero-setup local dev behavior for anyone who's never heard of
    this flag."""
    raw = os.environ.get(_DEV_AUTH_BYPASS_ENV)
    if raw is not None:
        return raw == "1"
    return store.using_local_store()


def verify_user(authorization: str | None = Header(default=None)) -> AuthUser:
    """FastAPI dependency: returns the verified caller, or raises 401/500."""
    if _dev_bypass_enabled():
        return AuthUser(rep_id="dev", email="dev@localhost", is_admin=True)

    keys = _key_map()
    if not keys:
        print(
            "[consultcastai] auth FAIL-CLOSED: CONSULTCASTAI_API_KEYS is unset and "
            "the dev bypass is off -> refusing with 500. For local dev set "
            "CONSULTCASTAI_LOCAL_STORE=1 (or CONSULTCASTAI_DEV_AUTH_BYPASS=1 "
            "explicitly); for a real deploy set the key map."
        )
        raise HTTPException(status_code=500, detail="Access control is not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()

    rep_id = keys.get(token)
    if not rep_id:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return AuthUser(rep_id=rep_id, email=f"{rep_id}@consultcastai", is_admin=rep_id in _admin_reps())


def require_owner(session_rep_id: str, user: AuthUser) -> None:
    """A rep may only touch their own sessions; admins bypass."""
    if user.is_admin:
        return
    if session_rep_id != user.rep_id:
        raise HTTPException(status_code=403, detail="Not your session")
