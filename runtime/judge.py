"""Arm-agnostic judgment surface for games.

Wraps TypeSafe `system_one` (or the baseline arm) and adds timing, caching, Weave
logging, and the arm switch. See BUILD.md section 5.

Build order: wire `choice()` to TypeSafe first (step 2). `noul`/`score` stay stubs
until a game needs them.
"""
from dataclasses import dataclass


@dataclass
class Result:
    pick: str | None = None
    dist: dict | None = None          # distribution over options
    confidence: float | None = None
    latency_ms: float | None = None
    cost: float | None = None
    arm: str | None = None


async def choice(key, state, instructions, criteria) -> Result:
    """One Choice judgment over `state`.

    TODO (step 2): call TypeSafe `system_one` via AsyncTypeSafeClient with a single
    Choice question; route by RUNTIME_ARM; time, cache, and log to Weave.
    """
    raise NotImplementedError("Build step 2: wire choice() to TypeSafe.")


async def ask(key, state, questions) -> dict:
    """Multiple questions over one shared `state` (used by Turing Tag later)."""
    raise NotImplementedError("stub — multi-question batching, not needed this slice")


async def noul(key, state, instructions, criteria=None) -> Result:
    raise NotImplementedError("stub — wire when a game needs it")


async def score(key, state, instructions, criteria) -> Result:
    raise NotImplementedError("stub — wire when a game needs it")
