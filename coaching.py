"""
Live coaching engine, rule-based, no AI call, so feedback is instant and
independent of the Claude round trip.

Tracks three signals per rep (consultant) message: Objection Pressure,
Trust, Specificity. Vocabulary is tuned for AI-consulting sales pitches
specifically, since that's a different jargon set than general B2B sales.
"""

import re
from dataclasses import dataclass

PRESSURE_START = 75    # lower is better
TRUST_START = 20        # higher is better
SPECIFICITY_START = 50  # higher is better

# AI-sales-specific buzzword list. Distinct from general sales jargon because
# the whole pitch is about AI, so generic AI marketing language is the actual
# tell of a weak, unspecific pitch here.
VAGUE_TERMS = [
    "revolutionize", "revolutionary", "game-changer", "game changer",
    "cutting-edge", "cutting edge", "next-level", "next level",
    "supercharge", "unlock", "leverage ai", "ai-powered", "ai powered",
    "disrupt", "seamless", "seamlessly", "transform your business",
    "future-proof", "future proof", "state-of-the-art", "world-class",
    "world class", "smart solution", "turnkey", "frictionless",
    "streamline", "synergy", "holistic", "robust", "scalable",
    "paradigm", "ecosystem", "circle back", "touch base",
]

_QUESTION_OPENERS = {
    "what", "how", "why", "when", "who", "where", "which",
    "do", "does", "did", "can", "could", "would", "will", "is", "are",
}


def _has_question(text: str) -> bool:
    if "?" in text:
        return True
    for sentence in re.split(r"[.!?;\n]+", text):
        words = sentence.strip().lower().split()
        if words and words[0].strip(",\"'()-") in _QUESTION_OPENERS:
            return True
    return False


@dataclass
class MessageFeatures:
    has_question: bool
    has_number: bool
    vague_count: int
    word_count: int


@dataclass
class CoachingState:
    pressure: int = PRESSURE_START
    trust: int = TRUST_START
    specificity: int = SPECIFICITY_START


@dataclass
class CoachingResult:
    state: CoachingState
    note_kind: str  # "good" | "warn" | "danger" | "neutral"
    note_text: str


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def score_message(text: str) -> MessageFeatures:
    lower = text.lower()
    has_question = _has_question(text)
    has_number = bool(re.search(r"\d", text))
    vague_count = sum(1 for term in VAGUE_TERMS if term in lower)
    word_count = len(text.strip().split())
    return MessageFeatures(has_question, has_number, vague_count, word_count)


def apply_deltas(state: CoachingState, features: MessageFeatures) -> CoachingState:
    pressure, trust, specificity = state.pressure, state.trust, state.specificity

    if features.has_number:
        pressure -= 10
        specificity += 12
    else:
        specificity -= 4

    if features.has_question:
        pressure -= 6
        trust += 10

    if features.vague_count >= 2:
        pressure += 8
        trust -= 8
        specificity -= 10

    if features.word_count > 60 and not features.has_question:
        pressure += 5
        trust -= 5

    if features.word_count < 5:
        trust -= 5

    return CoachingState(
        pressure=_clamp(pressure),
        trust=_clamp(trust),
        specificity=_clamp(specificity),
    )


def coaching_note(features: MessageFeatures, first_name: str) -> tuple[str, str]:
    """Priority order, first match wins."""
    if features.word_count < 5:
        return "warn", "Too short. Give them enough to actually engage with."
    if features.vague_count >= 2:
        return "danger", f"Drop the AI buzzwords, {first_name} can hear them."
    if features.has_number and features.has_question:
        return "good", "Strong move. Specific number plus a discovery question opens the door."
    if features.has_number:
        return "good", "Good specificity. Now ask a question to keep them talking."
    if features.has_question and features.word_count < 30:
        return "good", "Tight, focused question. That's how you earn the next minute."
    if features.word_count > 60 and not features.has_question:
        return "warn", "You're pitching, not selling. Ask something."
    return "neutral", "Decent. Add a number or a question to push it harder."


def evaluate(text: str, state: CoachingState, first_name: str) -> CoachingResult:
    features = score_message(text)
    new_state = apply_deltas(state, features)
    kind, note = coaching_note(features, first_name)
    return CoachingResult(state=new_state, note_kind=kind, note_text=note)
