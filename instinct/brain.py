"""Brain: NPC decisions from Jev that learn the player and never stall the game.

Give it the actions an NPC can take and a fallback. Each decision sends Jev the
NPC's situation plus everything learned about the player, and gets back the action
with a probability for every option. Calls run on a background thread, so a game
loop can `request()` a decision and `poll()` for it on a later frame.

A decision falls back instead of failing:
  - "timeout":        Jev took longer than `timeout_s`
  - "error":          the call raised, or returned an action you didn't offer
  - "low_confidence": the chosen action's probability was under `confidence_floor`,
                      so the NPC keeps its last action (or the fallback if it has none)
"""
import asyncio
import json
import logging
import os
import statistics
import threading
import time
from collections import Counter, deque
from concurrent.futures import Future
from dataclasses import dataclass, field

from .jev import JevDecider, Verdict
from .memory import LessonStore

log = logging.getLogger("instinct")


@dataclass(frozen=True)
class Decision:
    npc: str
    action: str
    source: str                     # "jev" or "fallback"
    reason: str | None = None       # set when source == "fallback"
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None
    latency_ms: float = 0.0
    lessons_used: int = 0
    error: str | None = None        # what went wrong, when reason == "error"

    @property
    def fell_back(self) -> bool:
        return self.source == "fallback"


class Brain:
    def __init__(
        self,
        actions: dict[str, str],
        *,
        instructions: str,
        fallback: str,
        memory: str = ":memory:",
        timeout_s: float = 1.0,
        confidence_floor: float = 0.4,
        decider=None,
        trace: bool = False,
    ):
        if not isinstance(actions, dict) or not actions:
            raise ValueError("actions must be a non-empty dict of {name: description}")
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in actions.items()):
            raise ValueError("actions keys and descriptions must be strings")
        if fallback not in actions:
            raise ValueError(f"fallback {fallback!r} must be one of the actions: {list(actions)}")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than 0")
        if not 0 <= confidence_floor <= 1:
            raise ValueError("confidence_floor must be between 0 and 1")
        if decider is None and not os.environ.get("TYPESAFE_API_KEY"):
            raise RuntimeError(
                "TYPESAFE_API_KEY is not set. Brain calls Jev by default; set the key, "
                "or pass your own decider."
            )

        self.actions = dict(actions)
        self.instructions = instructions
        self.fallback = fallback
        self.timeout_s = timeout_s
        self.confidence_floor = confidence_floor
        self._decider = decider or JevDecider()
        self._store = LessonStore(str(memory))

        self._lock = threading.Lock()
        self._pending: dict[str, Future] = {}
        self._last: dict[str, str] = {}
        self._latencies: deque[float] = deque(maxlen=1000)
        self._counts: Counter = Counter()
        self._logged_errors: set[str] = set()

        self._decide_op = self._decide
        if trace:
            import weave  # optional; call weave.init("entity/project") in your game first
            self._decide_op = weave.op(self._decide, name="instinct.decide")

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="instinct-brain", daemon=True)
        self._thread.start()

    # --- decisions ---------------------------------------------------------
    def request(self, npc: str, *, player: str, situation: dict) -> None:
        """Start a decision without waiting. A newer request for the same NPC replaces
        an older one that hasn't finished."""
        fut = self._submit(npc, player, situation)
        with self._lock:
            old = self._pending.get(npc)
            if old is not None and not old.done():
                old.cancel()
            self._pending[npc] = fut

    def poll(self, npc: str) -> Decision | None:
        """Return the NPC's decision once it's ready (once only), else None."""
        with self._lock:
            fut = self._pending.get(npc)
            if fut is None or not fut.done():
                return None
            del self._pending[npc]
        if fut.cancelled():
            return None
        return fut.result()

    def decide(self, npc: str, *, player: str, situation: dict) -> Decision:
        """Blocking version, for turn-based games and scripts. Bounded by timeout_s."""
        return self._submit(npc, player, situation).result()

    async def adecide(self, npc: str, *, player: str, situation: dict) -> Decision:
        """Async version, for games that run their own event loop."""
        return await asyncio.wrap_future(self._submit(npc, player, situation))

    # --- learning ----------------------------------------------------------
    def learn(self, player: str, lesson: str) -> bool:
        """Record what happened with this player. Every NPC sees it on its next decision.
        Returns False if the player already had this lesson."""
        if not isinstance(lesson, str) or not lesson.strip():
            raise ValueError("lesson must be a non-empty string")
        return self._store.add(player, lesson.strip())

    def lessons(self, player: str) -> list[str]:
        return self._store.get(player)

    def forget(self, player: str) -> None:
        self._store.forget(player)

    # --- health --------------------------------------------------------------
    def stats(self) -> dict:
        """Decision counts, fallbacks by reason, and latency over the last 1000 decisions."""
        with self._lock:
            lat = sorted(self._latencies)
            counts = dict(self._counts)
        out = {"decisions": counts.pop("decisions", 0), "fallbacks": counts}
        if lat:
            out["p50_ms"] = round(statistics.median(lat), 1)
            out["p95_ms"] = round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 1)
        return out

    def close(self) -> None:
        with self._lock:
            for fut in self._pending.values():
                fut.cancel()
            self._pending.clear()
        aclose = getattr(self._decider, "aclose", None)
        if aclose is not None:
            try:
                asyncio.run_coroutine_threadsafe(aclose(), self._loop).result(timeout=2)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
        self._store.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- internals -----------------------------------------------------------
    def _submit(self, npc: str, player: str, situation: dict) -> Future:
        if not isinstance(situation, dict):
            raise ValueError("situation must be a dict")
        try:
            json.dumps(situation)
        except (TypeError, ValueError) as e:
            raise ValueError(f"situation must be JSON-serializable: {e}") from None
        return asyncio.run_coroutine_threadsafe(self._decide_op(npc, player, situation), self._loop)

    async def _decide(self, npc: str, player: str, situation: dict) -> Decision:
        lessons = self._store.get(player)
        state = {"situation": situation, "this_player": {"id": player, "lessons": lessons}}
        t0 = time.perf_counter()
        try:
            v: Verdict = await asyncio.wait_for(
                self._decider(state, self.instructions, self.actions), self.timeout_s)
        except asyncio.TimeoutError:
            return self._record(npc, self.fallback, "fallback", "timeout", t0, len(lessons))
        except Exception as e:
            return self._record(npc, self.fallback, "fallback", "error", t0, len(lessons),
                                error=f"{type(e).__name__}: {e}")

        if v.action not in self.actions:
            return self._record(npc, self.fallback, "fallback", "error", t0, len(lessons),
                                error=f"decider returned {v.action!r}, which isn't one of the actions")
        if v.probabilities.get(v.action, 0.0) < self.confidence_floor:
            keep = self._last.get(npc, self.fallback)
            return self._record(npc, keep, "fallback", "low_confidence", t0, len(lessons), v)
        return self._record(npc, v.action, "jev", None, t0, len(lessons), v)

    def _record(self, npc, action, source, reason, t0, n_lessons, v: Verdict | None = None,
                error: str | None = None) -> Decision:
        ms = (time.perf_counter() - t0) * 1000.0
        with self._lock:
            self._latencies.append(ms)
            self._counts["decisions"] += 1
            if reason:
                self._counts[reason] += 1
            self._last[npc] = action
            first_time = error is not None and error not in self._logged_errors
            if first_time:
                self._logged_errors.add(error)
        if first_time:  # once per distinct error, so a bad key doesn't flood the log every frame
            log.warning("decision fell back to %r: %s", action, error)
        return Decision(
            npc=npc, action=action, source=source, reason=reason,
            probabilities=dict(v.probabilities) if v else {},
            confidence=v.confidence if v else None,
            latency_ms=ms, lessons_used=n_lessons, error=error,
        )
