"""
ConsultCastAI backend, AI Curator LLC.

AI-powered practice partner for AI consultants: pick a persona and a
scenario, hold a real spoken back-and-forth with a skeptical SMB owner,
get live coaching, get a debrief.

Draft status: solo-founder scale. No SSO, no secrets manager, no cloud
storage required by default, see README.md for the local -> production path.
"""

import os
import time

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware

import auth
import claude_client
import anam_client
import content
import coaching
import store
from models import (
    SessionRecord,
    ConversationTurn,
    StartSessionRequest,
    TurnRequest,
    TurnResponse,
    EndSessionResponse,
    AvatarTokenRequest,
    AvatarTokenResponse,
)
from prompts import build_system_prompt, build_debrief_prompt

app = FastAPI(title="ConsultCastAI Backend")

# CORS: locked to known frontend origins in production, open to localhost in
# dev. CONSULTCASTAI_ENV=production is the explicit signal, set it on whatever
# host serves this in prod. Since ConsultCastAI is hosted as a page/subpath on
# ai-curator.ai rather than its own domain for now, set
# CONSULTCASTAI_ALLOWED_ORIGINS to that site's origin (e.g.
# "https://www.ai-curator.ai"), not a dedicated ConsultCastAI domain.
_IS_PROD = os.environ.get("CONSULTCASTAI_ENV") == "production"
_PROD_ORIGINS = [
    o.strip() for o in os.environ.get("CONSULTCASTAI_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
if _IS_PROD:
    _ALLOWED_ORIGINS = _PROD_ORIGINS
    _ALLOW_ORIGIN_REGEX = None
else:
    _ALLOWED_ORIGINS = ["null"]
    _ALLOW_ORIGIN_REGEX = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"

print(
    f"[consultcastai] CORS mode: {'production' if _IS_PROD else 'local dev'}; "
    f"allowed_origins={_ALLOWED_ORIGINS}; localhost_regex={'on' if _ALLOW_ORIGIN_REGEX else 'off'}"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=_ALLOW_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
)

_coaching_state: dict[str, coaching.CoachingState] = {}
_start_time: dict[str, float] = {}


@app.get("/personas")
def list_personas():
    """Frontend catalog: personas + their active scenarios."""
    out = []
    for p in content.list_personas():
        scenarios = [s for s in content.list_active_scenarios() if s.persona_id == p.id]
        out.append({
            "id": p.id,
            "name": p.name,
            "role": p.role,
            "context": p.context,
            "traits": p.traits,
            "has_avatar": bool(p.avatar_id and p.voice_id),
            "scenarios": [
                {
                    "id": s.id, "title": s.title,
                    "group": s.group, "group_label": content.GROUPS.get(s.group, s.group),
                    "product": s.product, "opener": s.opener, "chips": s.chips,
                }
                for s in scenarios
            ],
        })
    return out


@app.post("/sessions", response_model=SessionRecord)
def start_session(req: StartSessionRequest, user: auth.AuthUser = Depends(auth.verify_user)):
    persona = content.get_persona(req.persona_id)
    scenario = content.get_scenario(req.scenario_id)
    if not persona or not scenario:
        raise HTTPException(404, "Persona or scenario not found (or scenario deactivated)")

    session = SessionRecord(
        rep_id=user.rep_id,
        persona_name=persona.name,
        persona_role=persona.role,
        scenario_title=scenario.title,
        scenario_product=scenario.product,
        voice_tier=req.voice_tier,
        active_scenario_id=scenario.id,
        conversation=[ConversationTurn(role="assistant", content=scenario.opener)],
    )
    store.save(session)
    _coaching_state[session.id] = coaching.CoachingState()
    _start_time[session.id] = time.time()

    return session


@app.post("/sessions/{session_id}/turn", response_model=TurnResponse)
def send_turn(session_id: str, req: TurnRequest, user: auth.AuthUser = Depends(auth.verify_user)):
    session = store.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    auth.require_owner(session.rep_id, user)

    persona = content.get_persona(_persona_id_for(session))
    scenario = content.get_scenario(session.active_scenario_id)
    if not persona or not scenario:
        raise HTTPException(409, "Persona or scenario no longer available")

    state = _coaching_state.setdefault(session_id, coaching.CoachingState())
    first_name = persona.name.split()[0]
    result = coaching.evaluate(req.message, state, first_name)
    _coaching_state[session_id] = result.state

    session.conversation.append(ConversationTurn(role="user", content=req.message))
    system_prompt = build_system_prompt(persona, scenario)
    history = [{"role": t.role, "content": t.content} for t in session.conversation]
    try:
        reply = claude_client.get_persona_reply(system_prompt, history)
    except Exception as exc:
        session.conversation.pop()  # drop the user turn we just appended, nothing was saved yet
        print(f"[consultcastai] persona reply call failed for session {session.id}: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="Persona reply temporarily unavailable")
    session.conversation.append(ConversationTurn(role="assistant", content=reply))

    session.pressure = result.state.pressure
    session.trust = result.state.trust
    session.specificity = result.state.specificity
    store.save(session)

    return TurnResponse(
        persona_reply=reply,
        pressure=result.state.pressure,
        trust=result.state.trust,
        specificity=result.state.specificity,
        coaching_note_kind=result.note_kind,
        coaching_note_text=result.note_text,
    )


@app.post("/sessions/{session_id}/end", response_model=EndSessionResponse)
def end_session(session_id: str, user: auth.AuthUser = Depends(auth.verify_user)):
    session = store.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    auth.require_owner(session.rep_id, user)

    persona = content.get_persona(_persona_id_for(session))
    scenario = content.get_scenario(session.active_scenario_id)

    started = _start_time.get(session_id, time.time())
    duration_sec = int(time.time() - started)
    session.duration_sec = duration_sec

    transcript_lines = [
        f"{'CONSULTANT' if t.role == 'user' else session.persona_name.upper()}: {t.content}"
        for t in session.conversation
    ]
    debrief_prompt = build_debrief_prompt(
        persona, scenario, transcript_lines,
        session.pressure, session.trust, session.specificity, duration_sec,
    )
    try:
        debrief = claude_client.get_debrief(debrief_prompt)
    except Exception as exc:
        print(f"[consultcastai] debrief call failed for session {session.id}: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="Debrief temporarily unavailable")
    session.debrief = debrief
    session.status = "completed"
    store.save(session)

    return EndSessionResponse(session_id=session.id, debrief=debrief, duration_sec=duration_sec)


@app.post("/avatar/session-token", response_model=AvatarTokenResponse)
def avatar_session_token(req: AvatarTokenRequest, user: auth.AuthUser = Depends(auth.verify_user)):
    """Mints a short-lived Anam live-avatar session token. Claude still
    drives every reply through /turn; Anam only renders face + voice."""
    persona = content.get_persona(req.persona_id)
    if persona is None:
        raise HTTPException(404, "Persona not found")
    if not persona.avatar_id or not persona.voice_id:
        raise HTTPException(409, "Persona has no Anam avatar configured yet")
    try:
        token = anam_client.mint_session_token(
            persona.name, persona.avatar_id, persona.voice_id, persona.avatar_model
        )
    except Exception as exc:
        print(f"[consultcastai] anam session-token call failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="Avatar session temporarily unavailable")
    return AvatarTokenResponse(session_token=token)


def _persona_id_for(session: SessionRecord) -> str:
    for pid, p in content.PERSONAS.items():
        if p.name == session.persona_name:
            return pid
    return ""
