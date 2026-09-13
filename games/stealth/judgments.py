"""The `stealth.guard_action` Choice, plus the code-side rules around it
(when to ask, threshold/hysteresis, hard overrides). See BUILD.md section 6.
"""
from runtime import judge

GUARD_ACTIONS = {
    "patrol":            "keep the normal patrol route",
    "investigate_noise": "go check the noise or anomaly",
    "chase":             "pursue the player directly",
    "call_backup":       "radio for backup",
    "return_to_post":    "go back to the assigned post",
}

CONFIDENCE_FLOOR = 0.4   # below this, keep current behavior (no twitchy flip-flops)


async def decide_guard_action(guard_state: dict):
    """Ask the judgment, then apply thresholds and hard overrides.

    TODO (step 4):
      - only call when something ambiguous happened (non-empty just_noticed / new sighting)
      - hard overrides first: player in view + alert -> "chase"; radio broken -> drop backup
      - res = await judge.choice("stealth.guard_action", guard_state,
            instructions="Given what this guard senses, what should it do right now?",
            criteria=GUARD_ACTIONS)
      - if res.dist[res.pick] < CONFIDENCE_FLOOR: keep current behavior
    """
    raise NotImplementedError("Build step 4: wire guard decisions to judge.choice.")
