"""Arm-agnostic judgment surface for games.

Wraps TypeSafe `system_one` (or the baseline arm) and adds timing, a short cache,
and the arm switch. Weave logging is added in step 5. See BUILD.md section 5.

Scaling: each call is one `system_one` request over one `state`. Run many guards
concurrently with `asyncio.gather` — the shared client below is safe to reuse.
"""
import hashlib
import json
import time
from dataclasses import dataclass

from typesafe_sdk import AsyncTypeSafeClient, Choice

from runtime import baseline, config


@dataclass
class Result:
    pick: str | None = None
    dist: dict | None = None            # {option: probability}
    confidence: float | None = None
    latency_ms: float | None = None
    cost: float | None = None           # TODO: derive from usage + pricing
    arm: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
    request_id: str | None = None


# --- shared async client, created lazily and reused across calls ---
_client: AsyncTypeSafeClient | None = None


def _client_or_create() -> AsyncTypeSafeClient:
    global _client
    if _client is None:
        config.require("TYPESAFE_API_KEY")   # clear error if the key is missing
        _client = AsyncTypeSafeClient()       # reads TYPESAFE_API_KEY from env
    return _client


async def aclose() -> None:
    """Close the shared client. Call once on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# --- tiny TTL cache keyed by (key, state hash) ---
_cache: dict[str, tuple[float, Result]] = {}


def _cache_key(key: str, state: dict) -> str:
    blob = json.dumps(state, sort_keys=True, default=str)
    return f"{key}:{hashlib.sha1(blob.encode()).hexdigest()}"


def _cache_get(ck: str) -> Result | None:
    hit = _cache.get(ck)
    if hit is None:
        return None
    ts, res = hit
    if time.monotonic() - ts > config.JUDGE_CACHE_TTL_S:
        _cache.pop(ck, None)
        return None
    return res


async def choice(key: str, state: dict, instructions: str, criteria) -> Result:
    """One Choice judgment over `state`. Returns a Result (see fields above).

    Routes to TypeSafe or the baseline arm by config.RUNTIME_ARM. Caches identical
    (key, state) for a short TTL so idle NPCs don't re-pay.
    """
    ck = _cache_key(key, state)
    cached = _cache_get(ck)
    if cached is not None:
        return cached

    t0 = time.perf_counter()
    if config.RUNTIME_ARM == "baseline":
        res = await baseline.choice(state, instructions, criteria)   # step 7
        res.arm = "baseline"
    else:
        client = _client_or_create()
        resp = await client.system_one(
            state=state,
            questions={key: Choice(instructions=instructions, criteria=criteria)},
        )
        ans = resp.choices[key]
        usage = getattr(resp, "usage", None)
        res = Result(
            pick=ans.choice,
            dist=dict(ans.probabilities),
            confidence=ans.confidence,
            arm="typesafe",
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            model=getattr(resp, "model", None),
            request_id=getattr(resp, "request_id", None),
        )
    res.latency_ms = (time.perf_counter() - t0) * 1000.0
    _cache[ck] = (time.monotonic(), res)
    return res


async def ask(key, state, questions) -> dict:
    """Multiple questions over one shared `state` (used by Turing Tag later)."""
    raise NotImplementedError("stub — multi-question batching, not needed this slice")


async def noul(key, state, instructions, criteria=None) -> Result:
    raise NotImplementedError("stub — wire when a game needs it")


async def score(key, state, instructions, criteria) -> Result:
    raise NotImplementedError("stub — wire when a game needs it")
