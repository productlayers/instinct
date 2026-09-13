"""Build the `guard_state` dict the judgment reads, from the game world.

See BUILD.md section 6 for the schema. Keep this the single place that turns world
facts into judgment state.
"""
from runtime import memory


def guard_state(guard, world, player_id: str) -> dict:
    """Assemble what one guard senses right now, plus learned player fields.

    TODO (step 4): fill from the real world, alertness, last sighting, this tick's
    anomalies (noises, a door left open), and memory.recall(player_id).
    """
    return {
        "guard": {
            "id": guard.id,
            "alertness": guard.alertness,          # "calm" | "wary" | "alert"
            "last_saw_player_secs": None,
            "post": guard.post,
        },
        "just_noticed": [],                        # e.g. "heard a clang to the NE"
        "sightings": {"player_in_view": False, "last_seen_desc": None},
        "this_player": memory.recall(player_id),   # learned tricks, etc.
        "policy": "call backup only after a direct sighting",
    }
