"""
Claude API integration. Claude is the sole conversation engine, both for
in-character persona replies and the end-of-session debrief.

Dependency-free (stdlib urllib) so this has no supply-chain surface beyond
what's already required. API key is server-side only, never sent to the
browser.
"""

import os
import json
import urllib.request
import urllib.error

_KEY_ENV = "ANTHROPIC_API_KEY"
_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-sonnet-4-6"  # keep in sync with whatever's current
_TIMEOUT = 30
_ANTHROPIC_VERSION = "2023-06-01"


def _require_key() -> str:
    api_key = (os.environ.get(_KEY_ENV) or "").strip()
    if not api_key:
        raise RuntimeError(
            f"{_KEY_ENV} not set. In production this comes from a secrets "
            "manager, never an env var checked into anything or a key file."
        )
    return api_key


def _call(system: str, messages: list[dict], max_tokens: int) -> str:
    api_key = _require_key()
    payload = json.dumps({
        "model": _MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }).encode("utf-8")
    request = urllib.request.Request(
        _API_URL,
        data=payload,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
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
        print(f"[consultcastai] claude HTTP {e.code}: {body}")
        raise
    blocks = data.get("content", [])
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    if not text:
        raise RuntimeError("Claude response contained no text content")
    return text.strip()


def get_persona_reply(system_prompt: str, history: list[dict]) -> str:
    """history is the full conversation, oldest first, roles user/assistant.
    The opener (assistant's first line) is part of history already."""
    return _call(system_prompt, history, max_tokens=300)


def get_debrief(debrief_prompt: str) -> str:
    return _call(
        "You are a precise, direct sales coach. Follow the requested format exactly.",
        [{"role": "user", "content": debrief_prompt}],
        max_tokens=600,
    )


def get_dynamic_hints(hints_system_prompt: str, transcript_text: str) -> list[str]:
    """Suggested next lines for the consultant, regenerated after every turn
    based on what the persona just actually said. Static hints go stale the
    moment the conversation moves past the opening line; this keeps them
    relevant turn to turn instead.

    Uses a dedicated coaching system prompt, NOT the persona's in-character
    prompt — that prompt explicitly forbids breaking character, which is
    exactly what's needed here (analyzing the exchange from the outside).
    transcript_text is a plain formatted string, not the raw role-based chat
    history, so Claude isn't confused into thinking it "said" Carla's lines
    under a different persona.

    Returns an empty list on any failure (bad JSON, empty response, etc.) —
    callers should treat that as "no hints available this turn" rather than
    retrying or falling back to stale content.
    """
    user_message = (
        f"Conversation so far:\n{transcript_text}\n\n"
        "Suggest exactly 3 short lines the consultant could say next to keep "
        "making real progress, specific numbers, sharp discovery questions, "
        "or direct answers to whatever objection was just raised. Not "
        "generic sales talk.\n\n"
        "Return ONLY a JSON array of 3 strings, nothing else, no markdown "
        "fences, no preamble. Example: "
        '["line one", "line two", "line three"]'
    )
    try:
        raw = _call(hints_system_prompt, [{"role": "user", "content": user_message}], max_tokens=250)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").removeprefix("json").strip()
        hints = json.loads(raw)
        if isinstance(hints, list) and all(isinstance(h, str) for h in hints):
            return hints[:3]
    except Exception as exc:
        print(f"[consultcastai] dynamic hints call failed, showing none this turn: {type(exc).__name__}: {exc}")
    return []


def get_assessment(assessment_prompt: str) -> str:
    """A real, client-facing deliverable, not a coaching artifact. Higher
    token budget than the debrief since it's a longer structured document,
    and a system prompt that emphasizes it's a genuine work product, not an
    exercise, no meta commentary, no hedging.

    max_tokens=2000: 900 was measured too low in practice and produced
    assessments that cut off mid-sentence partway through SUGGESTED NEXT
    STEPS, the last required section, unacceptable for something meant to
    be copied and sent to a real client as-is. Bumped again on top of the
    first fix to leave headroom for the added BROADER AI LANDSCAPE section
    (5-7 more bullet points) now that the structure is 6 sections, not 5."""
    return _call(
        "You are a senior AI consultant producing a real, sendable deliverable "
        "for an actual client. Follow the requested structure exactly. No "
        "meta commentary about being AI-generated, no placeholders.",
        [{"role": "user", "content": assessment_prompt}],
        max_tokens=2000,
    )
