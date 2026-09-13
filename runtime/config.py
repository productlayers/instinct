"""Runtime config: reads keys and settings from the environment only.

Never hardcode secrets. See BUILD.md section 4 (secrets and repo hygiene).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load the repo-root .env so every entrypoint gets keys regardless of the working
# directory. (python-dotenv's find_dotenv() searches from the caller's file, which is
# fragile across scripts; this is explicit and robust.)
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# which arm answers judgments: "typesafe" (default) or "baseline"
RUNTIME_ARM = os.environ.get("RUNTIME_ARM", "typesafe")

# short cache TTL for identical (key, state) judgments, in seconds. Low on purpose:
# credits are plentiful, so we refresh decisions rather than hold a stale one.
JUDGE_CACHE_TTL_S = float(os.environ.get("JUDGE_CACHE_TTL_S", "0.1"))

# baseline (LLM-as-judge) arm, via W&B Inference (OpenAI-compatible, uses WANDB_API_KEY)
BASELINE_MODEL = os.environ.get("BASELINE_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
WANDB_INFERENCE_BASE_URL = os.environ.get("WANDB_INFERENCE_BASE_URL", "https://api.inference.wandb.ai/v1")
WANDB_INFERENCE_PROJECT = os.environ.get("WANDB_INFERENCE_PROJECT", "")


def require(name: str) -> str:
    """Return env var `name`, or raise a clear error naming what's missing."""
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            "Copy .env.example to .env and fill it in (see BUILD.md section 4)."
        )
    return val
