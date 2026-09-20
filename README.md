# ConsultCastAI

AI-powered practice partner for AI consultants: rehearse objection handling
against skeptical SMB owners across industries before the real sales or
discovery call happens.

**AI Curator LLC**, built on the pattern from the original ConsultCastAI
Founding Document (Claude for conversation, live voice + avatar for
delivery), rebuilt from scratch here with fresh content and a lighter
auth/storage model suited to a solo-founder product rather than an
enterprise client deployment.

## Stack

- **Claude** (`claude_client.py`) — the sole conversation engine, both the
  in-character persona replies and the end-of-session debrief.
- **Anam** (`anam_client.py`) — live avatar (face + voice) only. Anam's own
  LLM is disabled (`llmId: "CUSTOMER_CLIENT_V1"`), Claude drives every word.
- **FastAPI** (`main.py`) — session lifecycle: start, turn, end.
- **Rule-based coaching** (`coaching.py`) — instant, local, no API round
  trip. Tracks Objection Pressure, Trust, Specificity per message.
- **Storage** (`store.py`) — local JSON file by default, swappable to
  Firestore with one env var when this needs to run on real infra.
- **Auth** (`auth.py`) — bearer API keys issued per consultant, swappable to
  real SSO later without touching any route.

## Content model

Six SMB personas (`content.py`), each anchored to a different industry and
a different core objection type: cost/ROI, "we already use ChatGPT," staff
job-loss fear, data privacy, staff adoption resistance, trust/accuracy.
Two scenarios per persona to start. Add more by extending `PERSONAS` and
`SCENARIOS`, nothing else needs to change.

## Running it locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here      # never commit this
export CONSULTCASTAI_LOCAL_STORE=1              # local JSON file, no cloud needed
uvicorn main:app --reload --port 8080
```

Open `index.html` directly in a browser (or serve it statically), point the
API base at `http://localhost:8080`. In local-store mode, auth is bypassed
(dev user), so no API key is required for local testing — the field is
still there for when you point the frontend at a deployed backend.

Endpoints:

- `GET /personas` — catalog for the frontend
- `POST /sessions` — start a session
- `POST /sessions/{id}/turn` — send a consultant message, get persona reply + coaching
- `POST /sessions/{id}/end` — end session, get debrief
- `POST /avatar/session-token` — mint an Anam session token (requires `ANAM_API_KEY` and a persona with `avatar_id`/`voice_id` set)

## Hosting

No dedicated domain purchased yet, and none needed to get running. Plan is
to host this as a page/subpath on **ai-curator.ai** for now (e.g.
`ai-curator.ai/consultcastai`), not `consultcastai.com` or similar. If that
changes later:

- `index.html` has no hardcoded domain assumptions, it just points at
  whatever `API_BASE` you type into the connect field (saved to
  `localStorage`), so it can be dropped into any static host or subpath
  as-is.
- The backend's CORS only needs to know the *frontend's* origin
  (`CONSULTCASTAI_ALLOWED_ORIGINS`), which will be `https://www.ai-curator.ai`
  while it lives there, not a ConsultCastAI-specific domain.

`consultcastai.com`, `.ai`, and `.io` were all open as of this check, worth
grabbing later if this becomes its own destination rather than a page on the
main site, domain squatting risk is low right now but not zero.

## Going from local to a real deployment

| Layer | Local default | Production |
|---|---|---|
| Storage | JSON file (`CONSULTCASTAI_LOCAL_STORE=1`) | Either stay on local-JSON with a persistent disk (see Render below), or set `CONSULTCASTAI_LOCAL_STORE=0` + `CONSULTCASTAI_FIRESTORE_PROJECT` for Firestore if this ever needs multiple instances |
| Auth | Dev bypass | Set `CONSULTCASTAI_API_KEYS="key:rep_id,..."`, and set `CONSULTCASTAI_DEV_AUTH_BYPASS=0` if still using local-JSON storage (the bypass otherwise defaults on whenever storage is local, see `auth.py`) |
| CORS | Open to localhost | Set `CONSULTCASTAI_ENV=production` + `CONSULTCASTAI_ALLOWED_ORIGINS` |
| Secrets | Env vars | Move `ANTHROPIC_API_KEY` / `ANAM_API_KEY` to a real secrets manager, or at minimum set them as Render's (non-synced) environment variables, never commit them |
| Avatar | Voice-only (browser TTS/STT) fallback works with zero Anam setup | Publish personas in Anam Lab, set `avatar_id`/`voice_id`/`avatar_model` per persona in `content.py` |

## Deploying to Render

`render.yaml` in the repo root is a Render Blueprint for the backend
(`consultcastai-api`): Python web service, local-JSON storage on a small
persistent disk (`/data`), real auth enforced
(`CONSULTCASTAI_DEV_AUTH_BYPASS=0`). No GCP/Firestore involved, this stays
entirely on Render.

To deploy: in the Render dashboard, New -> Blueprint, connect this repo.
Render will read `render.yaml` and prompt for the env vars marked
`sync: false` (never committed): `ANTHROPIC_API_KEY`, `ANAM_API_KEY`,
`CONSULTCASTAI_API_KEYS`, `CONSULTCASTAI_ADMIN_REPS` (optional), and
`CONSULTCASTAI_ALLOWED_ORIGINS` once the frontend has a home.

The static frontend (`index.html` + `assets/`) is not part of this
Blueprint on purpose, hosting it is a separate decision, its own Render
Static Site, a subdomain on ai-curator.ai (the pattern ClientBriefAI
already uses), or just opened locally against the deployed API for now.

## Voice, current state

The frontend uses the browser's built-in Web Speech API (`SpeechRecognition`
for mic input, `speechSynthesis` for the persona's voice) so the whole thing
works end-to-end with zero avatar vendor setup. Wiring in Anam's live avatar
is the next step once personas are published in Anam Lab: call
`POST /avatar/session-token`, feed the token to Anam's client SDK, and send
each `persona_reply` to Anam's `talk()` instead of (or alongside)
`speechSynthesis`.

## Ownership note

This is a from-scratch build for AI Curator LLC. It follows the same
architectural pattern (Claude + live avatar, rule-based live coaching, a
persona/scenario content model) documented in the original ConsultCastAI
Founding Document, but all content, prompts, and code here are written
fresh for this product, not reused from any client engagement.
