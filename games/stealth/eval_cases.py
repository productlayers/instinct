"""Golden cases for Stealth: (guard_state, expected_pick).

Drives three proofs off one set: decision accuracy, the A/B vs the LLM baseline, and
the learning curve (replayed with `this_player.tricks` accumulating). See BUILD.md
section 8. Seed set below, grow to ~12-15.
"""

CASES = [
    (
        {
            "guard": {"alertness": "calm", "last_saw_player_secs": None},
            "just_noticed": ["heard a clang to the NE"],
            "sightings": {"player_in_view": False, "last_seen_desc": None},
            "this_player": {},
            "policy": "call backup only after a direct sighting",
        },
        "investigate_noise",
    ),
    (
        {
            "guard": {"alertness": "calm", "last_saw_player_secs": None},
            "just_noticed": ["heard a clang to the NE"],
            "sightings": {"player_in_view": False, "last_seen_desc": None},
            "this_player": {"tricks": ["fake distraction via thrown object"]},
            "policy": "call backup only after a direct sighting",
        },
        "patrol",   # should not be baited once it knows this player
    ),
    (
        {
            "guard": {"alertness": "wary", "last_saw_player_secs": 6},
            "just_noticed": [],
            "sightings": {"player_in_view": False, "last_seen_desc": "west corridor"},
            "this_player": {},
            "policy": "call backup only after a direct sighting",
        },
        "investigate_noise",   # go to last seen, not call_backup (policy)
    ),
    (
        {
            "guard": {"alertness": "alert", "last_saw_player_secs": 0},
            "just_noticed": [],
            "sightings": {"player_in_view": True, "last_seen_desc": "right here"},
            "this_player": {},
            "policy": "call backup only after a direct sighting",
        },
        "chase",
    ),
    (
        {
            "guard": {"alertness": "calm", "last_saw_player_secs": None},
            "just_noticed": [],
            "sightings": {"player_in_view": False, "last_seen_desc": None},
            "this_player": {},
            "policy": "call backup only after a direct sighting",
        },
        "patrol",
    ),
]
