# Usage Metering Spec — ConsultCastAI

Ready for Claude Code to build against. Covers what needs to exist before
"$20/mo with limits" is a real, enforced thing rather than just pricing-page
copy.

## The core problem today

`auth.py` knows *who* a rep is. Nothing tracks *how much* they've used this
month, and nothing blocks them once they hit a cap. Every session and every
avatar minute is currently free to the rep and a real cost to you.

## Plan tiers (starting point, tune before launch)

| Plan | Price | Sessions/mo (text+voice) | Avatar minutes/mo |
|---|---|---|---|
| Starter | ~$20 | 50 | 0 (no avatar access) |
| Pro | ~$49–69 | 200 | 60 |
| Team | ~$99–149 | Unlimited* | 200, pooled across seats |

*"Unlimited" should still have a high hard ceiling (e.g. 1000/mo) as an
abuse backstop, not truly infinite.

Avatar minutes map directly to Anam's own metering, so Pro's 60 min/mo
should stay comfortably under whatever Anam plan you're paying for once
you have multiple Pro users sharing one Anam account's pool.

## Data model additions

**`models.py`** — new record, one per rep per calendar month:

```python
class UsageRecord(BaseModel):
    rep_id: str
    month: str  # "2026-08" format, UTC calendar month
    session_count: int = 0
    avatar_seconds: int = 0
```

## Plan config

**New file `plans.py`** — keeps limits out of business logic, easy to tune
without touching enforcement code:

```python
PLANS = {
    "starter": {"max_sessions": 50, "max_avatar_seconds": 0},
    "pro": {"max_sessions": 200, "max_avatar_seconds": 60 * 60},
    "team": {"max_sessions": 1000, "max_avatar_seconds": 200 * 60},
}
DEFAULT_PLAN = "starter"

def plan_for(rep_id: str) -> str:
    # Simplest MVP: env var mapping "rep_id:plan,rep_id:plan".
    # Swap for a real billing/subscription lookup later without touching
    # any of the enforcement code below.
    import os
    raw = os.environ.get("CONSULTCASTAI_PLANS", "")
    mapping = dict(p.split(":") for p in raw.split(",") if ":" in p)
    return mapping.get(rep_id, DEFAULT_PLAN)
```

## Store additions

**`store.py`** — same local-file/Firestore dual-mode pattern already used
for sessions, keyed by `f"{rep_id}:{month}"`:

```python
def get_usage(rep_id: str, month: str) -> UsageRecord: ...
def increment_session_count(rep_id: str, month: str) -> UsageRecord: ...
def add_avatar_seconds(rep_id: str, month: str, seconds: int) -> UsageRecord: ...
```

## Enforcement points in `main.py`

**`POST /sessions`** (before creating a session):
```python
usage = store.get_usage(user.rep_id, current_month())
plan = plans.PLANS[plans.plan_for(user.rep_id)]
if usage.session_count >= plan["max_sessions"]:
    raise HTTPException(429, "Monthly session limit reached. Resets on the 1st.")
store.increment_session_count(user.rep_id, current_month())
```

**`POST /avatar/session-token`** (before minting):
```python
usage = store.get_usage(user.rep_id, current_month())
plan = plans.PLANS[plans.plan_for(user.rep_id)]
if usage.avatar_seconds >= plan["max_avatar_seconds"]:
    raise HTTPException(429, "Monthly avatar minutes used up. Falls back to voice.")
```
Frontend already treats a failed avatar start as "fall back to voice" — this
409/429 slots into that existing path with zero new frontend error-handling
needed, just a clearer message.

**New endpoint `POST /avatar/usage`** — the backend can't see how long an
Anam stream actually ran (that happens client-side via the SDK), so the
frontend needs to report it:
```python
@app.post("/avatar/usage")
def report_avatar_usage(req: AvatarUsageRequest, user: AuthUser = Depends(auth.verify_user)):
    store.add_avatar_seconds(user.rep_id, current_month(), req.seconds)
```

**Frontend change** — `stopAvatar()` needs to track elapsed time and report
it:
```javascript
let avatarStartedAt = null;
// in startAvatar(), after a successful connection:
avatarStartedAt = Date.now();
// in stopAvatar(), before clearing state:
if(avatarStartedAt){
  const seconds = Math.round((Date.now() - avatarStartedAt) / 1000);
  api('/avatar/usage', { method: 'POST', body: JSON.stringify({ seconds }) }).catch(()=>{});
  avatarStartedAt = null;
}
```
This also needs to fire from the existing `beforeunload`/`pagehide`
listeners, not just the manual mode-switch path, so minutes still get
counted if someone just closes the tab mid-avatar-session.

## Open decisions before building

1. **Month boundary**: calendar month in UTC is simplest (`datetime.utcnow().strftime("%Y-%m")`), but means everyone's reset lands on the 1st regardless of signup date. Fine for a solo/small-cohort product; a real "billing anniversary" reset is more work and only matters once you have paying customers who'd notice.
2. **What happens at the cap**: hard block (what's specced above) vs. soft warn-then-allow. Hard block is simpler and protects your margin; worth adding a `GET /usage` endpoint so the frontend can show "42/50 sessions used" before they hit the wall, rather than surprising them.
3. **Plan assignment today**: the env-var mapping above is fine for you manually running a handful of pilot users. The moment you have any kind of signup flow or real billing (Stripe, etc.), `plan_for()` needs to look up a real subscription record instead — but nothing else in this spec changes when that happens, it's isolated to that one function.
