"""
Anam live-avatar session tokens for ConsultCastAI.

Anam provides the live avatar (face + voice) ONLY; Claude stays the sole
conversation engine. Anam's own model is disabled by sending
llmId "CUSTOMER_CLIENT_V1" in personaConfig, so the avatar only speaks text
the app sends it.

This mints a short-lived session token server-side and returns ONLY that
token to the caller; the Anam API key never reaches the browser.
"""

import os
import json
import urllib.request
import urllib.error

_KEY_ENV = "ANAM_API_KEY"
_API_URL = "https://api.anam.ai/v1/auth/session-token"
_TIMEOUT = 30

_LLM_ID = "CUSTOMER_CLIENT_V1"


def _require_key() -> str:
    api_key = (os.environ.get(_KEY_ENV) or "").strip()
    if not api_key:
        raise RuntimeError(
            f"{_KEY_ENV} not set. In production this comes from a secrets "
            "manager, server-side only."
        )
    return api_key


def mint_session_token(name: str, avatar_id: str, voice_id: str, avatar_model: str = "") -> str:
    """POST personaConfig to Anam and return ONLY the session token."""
    api_key = _require_key()
    persona_config = {
        "name": name,
        "avatarId": avatar_id,
        "voiceId": voice_id,
        "llmId": _LLM_ID,
    }
    if avatar_model:
        persona_config["avatarModel"] = avatar_model
    print(f"[consultcastai] anam personaConfig sent: {json.dumps(persona_config)}")
    payload = json.dumps({"personaConfig": persona_config}).encode("utf-8")
    request = urllib.request.Request(
        _API_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        print(f"[consultcastai] anam session-token HTTP {e.code}: {body}")
        raise
    token = data.get("sessionToken")
    if not token:
        raise RuntimeError("Anam response contained no sessionToken")
    return token
