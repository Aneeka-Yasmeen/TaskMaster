"""State schema: the fields a project state holds, and the vocabulary of state transitions.

The state is a set of *claims*. A claim is one belief about the project (e.g. "current blocker is
a timing violation") with provenance: which evidence supports it, whether that evidence verifies it
or merely reports it, and when it stopped being true. Claims are never deleted; they are superseded,
invalidated, or resolved, so the full belief history stays auditable.
"""

SCALAR_FIELDS = ("goal", "last_action", "current_status", "current_blocker", "next_step")
LIST_FIELDS = ("open_questions", "decisions", "attempts")
KEYED_FIELDS = ("status_items",)
ALL_FIELDS = SCALAR_FIELDS + LIST_FIELDS + KEYED_FIELDS

OPS = ("ADD", "UPDATE", "INVALIDATE", "CONTRADICT", "RESOLVE", "NOOP")

# Sources that are machine-produced artifacts. Only these can make a claim "verified".
# A note, chat message or meeting summary can only make a claim "reported".
VERIFIABLE_SOURCES = {
    "git_commit",
    "sim_log",
    "test_output",
    "ci",
    "synthesis_report",
    "implementation_report",
    "timing_report",
    "experiment_log",
    "report",
}
REPORTED_SOURCES = {"note", "chat", "meeting", "email", "issue"}
ALL_SOURCES = sorted(VERIFIABLE_SOURCES | REPORTED_SOURCES)

VERIFICATION_LEVELS = ("verified", "reported", "inferred")
CONFIDENCE_LEVELS = ("low", "medium", "high")
CONFIDENCE_RANK = {c: i for i, c in enumerate(CONFIDENCE_LEVELS)}
# A claim cannot be more confident than its verification level allows.
CONFIDENCE_CAP = {"verified": "high", "reported": "medium", "inferred": "low"}

MAX_OPS_PER_EVENT = 14
MAX_VALUE_CHARS = 400

FIELD_LABELS = {
    "goal": "Goal",
    "last_action": "Last action",
    "current_status": "Current status",
    "current_blocker": "Current blocker",
    "next_step": "Next step",
    "open_questions": "Open questions",
    "decisions": "Decisions",
    "attempts": "Attempts",
    "status_items": "Status",
}


def empty_state(project):
    return {
        "project": project,
        "version": 0,
        "last_event_id": None,
        "last_updated": None,
        "claims": {},
        "contradictions": {},
        "next_claim": 1,
        "next_contradiction": 1,
    }
