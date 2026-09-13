"""The learning loop.

`recall()` injects learned fields into a judgment's state before it runs.
`distill()` summarizes an attempt into those fields afterwards (offline, never in the
frame path). A "lesson" is just named fields we merge into future state — no model
retraining. See BUILD.md section 6.
"""


def recall(entity_id: str) -> dict:
    """Return learned fields for this entity (e.g. a player's known tricks).

    Empty dict if we've learned nothing yet.
    """
    return {}


def distill(entity_id: str, attempt_log: list) -> None:
    """Summarize what happened this attempt into stored fields for `entity_id`.

    TODO (step 6): e.g. detect a thrown-object distraction and add
    "fake distraction via thrown object" to the player's tricks.
    """
    raise NotImplementedError("Build step 6: distill lessons from an attempt.")
