"""Question answering.

The core questions are answered deterministically from the validated state. Other questions go
to the model with the state and evidence as context; citations in its answer are then checked
against the evidence store and invented ones are flagged.

Answers are returned as structured data (headline, text, cited evidence, suggested next step) so
the UI can show the reasoning next to the evidence instead of as a chat bubble.
"""

import re

from . import view as V
from .llm import LLMError
from .prompts import ANSWER_SYSTEM, render_event, render_state_for_prompt

INTENTS = [
    ("reversed", ("reversed", "abandon", "changed my mind", "undone", "reverted", "superseded")),
    ("why", ("why", "evidence for", "how do you know", "what supports", "source of")),
    ("blocker", ("block", "stuck", "problem", "issue")),
    ("tried", ("try", "tried", "attempt", "history", "already done")),
    ("next", ("next", "should i do", "todo", "to do")),
    ("where", ("where am i", "where was i", "where did i", "status", "overview", "catch me up",
               "left off", "summary", "state")),
]

QUICK_QUESTIONS = ["Where did I leave off?", "What is blocking this project?", "What have I already tried?",
                   "What should I do next?", "Why do you believe the current blocker?",
                   "Show me decisions that were later reversed"]


def classify(question):
    q = question.lower()
    for intent, keys in INTENTS:
        if any(k in q for k in keys):
            return intent
    return "free"


def _why_target(question):
    q = re.sub(r"(?i)^\s*why (does|do|is|did) (the system|you|it|taskmaster)? ?(believe|think|say)?( that)?", "", question)
    q = re.sub(r"(?i)^\s*(what supports|evidence for|how do you know)( that)?", "", q)
    q = re.sub(r"(?i)\b(is|are) (the )?(current )?(blocker|problem)$", "", q.strip(" ?.")) or q
    return q.strip(" ?.") or "current_blocker"


HEADLINES = {
    "where": "Here is where the project stands",
    "blocker": "What is blocking progress",
    "tried": "What has already been tried",
    "next": "What to do next",
    "why": "Why TaskMaster believes this",
    "reversed": "Decisions that were reversed or abandoned",
}


def _structure(intent, text, view, events, mode):
    cited = sorted(set(re.findall(r"\bE\d+\b", text)), key=lambda e: int(e[1:]))
    nxt = view["fields"]["next_step"][0] if view["fields"]["next_step"] else None
    headline = HEADLINES.get(intent, "Answer")
    blocker = view["fields"]["current_blocker"]
    if intent in ("where", "blocker"):
        headline = (f"Blocked: {blocker[0]['value']}" if blocker else "No active blocker")
    return {
        "intent": intent, "mode": mode, "headline": headline, "text": text,
        "citations": [events[e] for e in cited if e in events],
        "next_step": {"value": nxt["value"], "evidence": nxt["evidence"],
                      "verification": nxt["verification"]} if nxt else None,
    }


def answer(store, project, question, llm=None, now=None):
    state = store.latest_state(project)
    events = store.events_by_id(project)
    view = V.build_view(state)
    intent = classify(question)
    renderers = {
        "where": lambda: V.where_am_i(view, now=now, name=store.project_name(project)),
        "blocker": lambda: V.what_blocks_me(view),
        "tried": lambda: V.what_did_i_try(view),
        "next": lambda: V.what_next(view),
        "why": lambda: V.explain(state, events, _why_target(question)),
        "reversed": lambda: V.what_was_reversed(view),
    }
    if intent == "why" and "blocker" in question.lower() and not view["fields"]["current_blocker"]:
        # false premise: don't explain an unrelated claim, say there is no blocker and show the last one
        ended = sorted((c for c in view["ended"] if c["field"] == "current_blocker"), key=lambda c: c["as_of"])
        text = "There is no active blocker right now."
        if ended:
            last = ended[-1]
            text += (f"\nThe most recent blocker was: {last['value']} {V.cite(last['evidence'])}"
                     f"\nIt stopped being current at {last['ended_by']}: {last.get('end_reason') or ''} {V.cite([last['ended_by']])}")
        out = _structure("why", text, view, events, "rendered from validated state")
        out["headline"] = "No active blocker"
        return out
    if intent in renderers:
        return _structure(intent, renderers[intent](), view, events, "rendered from validated state")
    return _free_answer(state, view, events, question, llm)


def _free_answer(state, view, events, question, llm):
    if llm is None:
        return _structure("free", "Free-form questions need the model, which is not available in this mode. "
                          "Try one of the suggested questions; they are answered from the validated state.",
                          view, events, "unavailable")
    context = (f"PROJECT STATE\n{render_state_for_prompt(state)}\n\nEVIDENCE LOG\n"
               + "\n".join(render_event(e, full=False) for e in list(events.values())[-40:])
               + f"\n\nQUESTION: {question}")
    try:
        text = llm.chat(ANSWER_SYSTEM, context, max_tokens=1200)
    except LLMError as e:
        return _structure("free", f"The model could not answer right now ({str(e)[:160]}).", view, events, "error")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    cited = set(re.findall(r"\bE\d+\b", text))
    invented = sorted(c for c in cited if c not in events)
    if invented:
        text += f"\n\n[validator] cited evidence that does not exist: {', '.join(invented)}"
    if not cited:
        text += "\n\n[validator] this answer cites no evidence; treat it as unsupported."
    out = _structure("free", text, view, events, f"generated by {llm.name}, citations checked")
    out["invented_citations"] = invented
    return out
