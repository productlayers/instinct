"""Build the `guard_state` dict the judgment reads, from the game world.

The single place that turns world facts into judgment state. See BUILD.md section 6.
"""
from runtime import memory

ALERT_NAMES = ("calm", "wary", "alert")


def guard_state(guard, noticed: list[str], player_id: str = "player") -> dict:
    """What this guard senses right now, plus any learned facts about the player."""
    return {
        "guard": {
            "alertness": ALERT_NAMES[max(0, min(2, guard.alert))],
            "post": str(guard.waypoints[0]),
        },
        "just_noticed": list(noticed),
        "sightings": {"player_in_view": False, "last_seen_desc": None},
        "this_player": memory.recall(player_id),   # learned tricks; empty until step 6
        "policy": "call backup only after a direct sighting",
    }
