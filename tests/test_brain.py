"""Brain tests. Jev is replaced by a fake decider, so these run without an API key."""
import asyncio
import time

import pytest

from instinct import Brain, Verdict

ACTIONS = {
    "investigate": "go check the noise",
    "hold": "stay at the post",
    "chase": "chase the player",
}
SITUATION = {"just_noticed": ["a clang to the side"]}


class FakeJev:
    """Picks `investigate` unless the player has a lesson on record. Records every state."""

    def __init__(self, delay=0.0, raises=None, verdict=None):
        self.delay, self.raises, self.verdict = delay, raises, verdict
        self.states = []

    async def __call__(self, state, instructions, actions):
        self.states.append(state)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises:
            raise self.raises
        if self.verdict:
            return self.verdict
        if state["this_player"]["lessons"]:
            return Verdict("hold", {"investigate": 0.05, "hold": 0.9, "chase": 0.05}, 0.9)
        return Verdict("investigate", {"investigate": 0.9, "hold": 0.05, "chase": 0.05}, 0.9)


def make(decider, **kw):
    kw.setdefault("instructions", "decide")
    kw.setdefault("fallback", "hold")
    return Brain(ACTIONS, decider=decider, **kw)


def test_decision_comes_from_jev():
    with make(FakeJev()) as b:
        d = b.decide("guard_1", player="p1", situation=SITUATION)
    assert d.action == "investigate"
    assert d.source == "jev" and not d.fell_back
    assert d.probabilities["investigate"] == 0.9


def test_request_does_not_block_the_game_loop():
    with make(FakeJev(delay=0.3)) as b:
        t0 = time.perf_counter()
        b.request("guard_1", player="p1", situation=SITUATION)
        assert time.perf_counter() - t0 < 0.05       # returned right away
        assert b.poll("guard_1") is None              # not ready on this frame
        deadline = time.perf_counter() + 2
        d = None
        while d is None and time.perf_counter() < deadline:
            d = b.poll("guard_1")
            time.sleep(0.01)
    assert d is not None and d.action == "investigate"


def test_poll_returns_a_decision_once():
    with make(FakeJev()) as b:
        b.request("guard_1", player="p1", situation=SITUATION)
        time.sleep(0.1)
        assert b.poll("guard_1") is not None
        assert b.poll("guard_1") is None


def test_slow_jev_falls_back_instead_of_stalling():
    with make(FakeJev(delay=1.0), timeout_s=0.05) as b:
        t0 = time.perf_counter()
        d = b.decide("guard_1", player="p1", situation=SITUATION)
        took = time.perf_counter() - t0
    assert d.action == "hold" and d.reason == "timeout"
    assert took < 0.5


def test_jev_error_falls_back():
    with make(FakeJev(raises=ConnectionError("down"))) as b:
        d = b.decide("guard_1", player="p1", situation=SITUATION)
    assert d.action == "hold" and d.reason == "error"


def test_unknown_action_from_decider_falls_back():
    bad = Verdict("dance", {"dance": 1.0}, 1.0)
    with make(FakeJev(verdict=bad)) as b:
        d = b.decide("guard_1", player="p1", situation=SITUATION)
    assert d.action == "hold" and d.reason == "error"


def test_low_confidence_keeps_the_last_action():
    unsure = Verdict("chase", {"investigate": 0.3, "hold": 0.35, "chase": 0.35}, 0.1)
    fake = FakeJev()
    with make(fake) as b:
        first = b.decide("guard_1", player="p1", situation=SITUATION)   # investigate
        fake.verdict = unsure
        second = b.decide("guard_1", player="p1", situation=SITUATION)
    assert first.action == "investigate"
    assert second.action == "investigate" and second.reason == "low_confidence"


def test_learning_changes_the_next_decision():
    fake = FakeJev()
    with make(fake) as b:
        before = b.decide("guard_1", player="p1", situation=SITUATION)
        b.learn("p1", "fakes distractions to get past guards")
        after = b.decide("guard_1", player="p1", situation=SITUATION)
    assert before.action == "investigate"
    assert after.action == "hold" and after.lessons_used == 1
    assert fake.states[-1]["this_player"]["lessons"] == ["fakes distractions to get past guards"]


def test_one_npcs_lesson_reaches_every_npc():
    with make(FakeJev()) as b:
        b.learn("p1", "fakes distractions")
        other = b.decide("guard_2", player="p1", situation=SITUATION)
        stranger = b.decide("guard_2", player="p2", situation=SITUATION)
    assert other.action == "hold"            # never saw the trick, still not fooled
    assert stranger.action == "investigate"  # lessons are per player


def test_learning_survives_a_restart(tmp_path):
    db = str(tmp_path / "npc.db")
    with make(FakeJev(), memory=db) as b:
        b.learn("p1", "fakes distractions")
    with make(FakeJev(), memory=db) as b:    # new process, same file
        assert b.lessons("p1") == ["fakes distractions"]
        d = b.decide("guard_1", player="p1", situation=SITUATION)
    assert d.action == "hold"


def test_learn_is_idempotent_and_forget_clears():
    with make(FakeJev()) as b:
        assert b.learn("p1", "fakes distractions") is True
        assert b.learn("p1", "fakes distractions") is False
        b.forget("p1")
        assert b.lessons("p1") == []


def test_stats_count_fallbacks():
    with make(FakeJev(raises=RuntimeError("x"))) as b:
        b.decide("guard_1", player="p1", situation=SITUATION)
        b.decide("guard_1", player="p1", situation=SITUATION)
        s = b.stats()
    assert s["decisions"] == 2 and s["fallbacks"] == {"error": 2}
    assert "p95_ms" in s


def test_async_games_can_await():
    async def run():
        with make(FakeJev()) as b:
            return await b.adecide("guard_1", player="p1", situation=SITUATION)
    assert asyncio.run(run()).action == "investigate"


@pytest.mark.parametrize("kwargs, err", [
    (dict(fallback="fly"), ValueError),
    (dict(timeout_s=0), ValueError),
    (dict(confidence_floor=2), ValueError),
])
def test_bad_config_fails_fast(kwargs, err):
    with pytest.raises(err):
        make(FakeJev(), **kwargs)


def test_bad_input_fails_fast():
    with make(FakeJev()) as b:
        with pytest.raises(ValueError):
            b.request("guard_1", player="p1", situation="not a dict")
        with pytest.raises(ValueError):
            b.request("guard_1", player="p1", situation={"obj": object()})
        with pytest.raises(ValueError):
            b.learn("p1", "   ")


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        Brain(ACTIONS, instructions="decide", fallback="hold")
