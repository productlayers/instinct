"""Weave tracing helpers, so every judgment is logged with inputs, pick, full
distribution, latency, cost, and arm. Never log secrets. See BUILD.md section 7.
"""


def init(project: str = "instinct-stealth") -> None:
    """TODO (step 5): weave.init(project)."""
    raise NotImplementedError("Build step 5: weave.init().")


def log_judgment(**fields) -> None:
    """TODO (step 5): record one judgment (key, state summary, pick, dist, latency,
    cost, arm) to Weave."""
    raise NotImplementedError("Build step 5: log a judgment to Weave.")
