"""Runtime config: reads keys and settings from the environment only.

Never hardcode secrets. See BUILD.md section 4 (secrets and repo hygiene).
"""
import os

# which arm answers judgments: "typesafe" (default) or "baseline"
RUNTIME_ARM = os.environ.get("RUNTIME_ARM", "typesafe")

# short cache TTL for identical (key, state) judgments, in seconds
JUDGE_CACHE_TTL_S = float(os.environ.get("JUDGE_CACHE_TTL_S", "0.5"))

# baseline (LLM-as-judge) model
BASELINE_MODEL = os.environ.get("BASELINE_MODEL", "claude-haiku-4-5-20251001")


def require(name: str) -> str:
    """Return env var `name`, or raise a clear error naming what's missing."""
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            "Copy .env.example to .env and fill it in (see BUILD.md section 4)."
        )
    return val
