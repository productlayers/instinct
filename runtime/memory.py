"""The learning loop.

`recall()` injects what we have learned about a player into a judgment's state before
it runs. `distill()` records a lesson after the fact (offline, never in the frame path).
A "lesson" is just named fields we merge into future state, so the same fast judgment
gets smarter with no model retraining. See BUILD.md section 6.

This is a simple in-memory store keyed by player id. It is the whole self-improvement
loop: catch the player using a trick once, remember it, and the next judgment weighs it.
"""

_store: dict[str, dict] = {}


def recall(player_id: str) -> dict:
    """Return learned fields for this player (e.g. known tricks). Empty if none yet."""
    return {k: (list(v) if isinstance(v, list) else v) for k, v in _store.get(player_id, {}).items()}


def learn_trick(player_id: str, trick: str) -> None:
    """Record a trick this player used. Idempotent."""
    tricks = _store.setdefault(player_id, {}).setdefault("tricks", [])
    if trick not in tricks:
        tricks.append(trick)


def distill(player_id: str, attempt_log) -> None:
    """Summarize an attempt into stored fields. For now the demo calls learn_trick
    directly; this stays as the general entry point (a real version would summarize a
    transcript into lessons)."""
    for trick in attempt_log or []:
        learn_trick(player_id, trick)


def reset(player_id: str | None = None) -> None:
    if player_id is None:
        _store.clear()
    else:
        _store.pop(player_id, None)
