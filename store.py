"""
Session storage for ConsultCastAI.

Default mode: local JSON file, zero infra to get running. Set
CONSULTCASTAI_LOCAL_STORE=0 and provide CONSULTCASTAI_FIRESTORE_PROJECT to switch to
Firestore once this needs to run on real infrastructure (Cloud Run, multiple
devices, real reps). The public API (save/get/list_for_rep) doesn't change
either way, so nothing above this module needs to know which backend is live.

Local mode has no concurrency safety and no retention policy, fine for a
solo founder testing against himself, not fine for real customer data.
"""

import os
import json
import threading
from pathlib import Path

from models import SessionRecord

_PROJECT_ID = os.environ.get("CONSULTCASTAI_FIRESTORE_PROJECT")
_COLLECTION = "sessions"

_LOCAL = os.environ.get("CONSULTCASTAI_LOCAL_STORE", "1") == "1"
_LOCAL_PATH = Path(os.environ.get("CONSULTCASTAI_LOCAL_STORE_PATH", "sessions_local.json"))
_LOCAL_LOCK = threading.Lock()

_client = None


def using_local_store() -> bool:
    return _LOCAL


# --- local file backend --------------------------------------------------

def _local_read_all() -> dict:
    if not _LOCAL_PATH.exists():
        return {}
    try:
        return json.loads(_LOCAL_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print(f"[consultcastai] {_LOCAL_PATH} was unreadable, starting a fresh local store.")
        return {}


def _local_write_all(data: dict) -> None:
    _LOCAL_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --- Firestore backend (optional, production) -----------------------------

def _get_client():
    global _client
    if _client is None:
        from google.cloud import firestore
        _client = firestore.Client(project=_PROJECT_ID) if _PROJECT_ID else firestore.Client()
    return _client


# --- public API -------------------------------------------------------

def save(session: SessionRecord) -> None:
    if _LOCAL:
        with _LOCAL_LOCK:
            data = _local_read_all()
            data[session.id] = session.model_dump()
            _local_write_all(data)
        return
    _get_client().collection(_COLLECTION).document(session.id).set(session.model_dump())


def get(session_id: str) -> SessionRecord | None:
    if _LOCAL:
        with _LOCAL_LOCK:
            raw = _local_read_all().get(session_id)
        return SessionRecord(**raw) if raw else None
    doc = _get_client().collection(_COLLECTION).document(session_id).get()
    if not doc.exists:
        return None
    return SessionRecord(**doc.to_dict())


def list_for_rep(rep_id: str) -> list[SessionRecord]:
    if _LOCAL:
        with _LOCAL_LOCK:
            data = _local_read_all()
        return [SessionRecord(**r) for r in data.values() if r.get("rep_id") == rep_id]
    docs = _get_client().collection(_COLLECTION).where("rep_id", "==", rep_id).stream()
    return [SessionRecord(**d.to_dict()) for d in docs]
