# Instinct — Stealth slice build doc

The goal of this slice: one small stealth game where the guards decide what to do
via TypeSafe typed judgments, running through a shared runtime module we can reuse
for the next game. When this slice is done we can demo the whole pitch on one game,
and Turing Tag becomes "do it again through the same module."

Everything here is Stealth-only. Turing Tag, Survival, Unity/Unreal, and any NPC
dialogue are out of scope for this slice.

**Local only.** The game never gets deployed. It runs on a laptop for play and for
screen-recording the demo — no hosting, no player accounts, no web build. That drops
a whole class of work (auth, servers, a JS build) and one class of on-stage failure.
The only network calls are to TypeSafe, OpenRouter (baseline), and W&B.

---

## 1. What "done" means (definition of done)

- [ ] A playable top-down stealth level: sneak past guards to reach the exit.
- [ ] Guards decide their behavior from a TypeSafe **Choice** judgment, not a script.
- [ ] The judgment runs off the frame loop (async) so it never stalls rendering.
- [ ] "The trick that stops working": a distraction that fools a guard on attempt 1,
      and stops fooling it after the guard has learned the player across attempts.
- [ ] An arm switch: the same guard decision can be answered by TypeSafe **or** by a
      plain LLM-as-judge, chosen by one config flag.
- [ ] Every judgment is logged to W&B Weave: inputs, pick, full distribution,
      latency, cost, and which arm answered.
- [ ] An evals script that runs the golden cases through both arms and prints
      accuracy, latency (p50/p95), cost, and the A/B deltas.
- [ ] No secrets in the repo. Keys come from the environment only.

Nice-to-have for this slice (first on the cut list):
- [ ] A marimo notebook to edit the judgment and watch a guard's decision change live.

---

## 2. Stack

Python everywhere — it lines up with all three sponsors (Weave and marimo are
Python-first, TypeSafe has a Python SDK) and keeps the demo self-contained.
Requires Python 3.10+ (`typesafe-sdk`); we're on 3.12. Verified installed:
typesafe-sdk 0.5.7, anthropic 1.5.0, weave 0.53.9, marimo 0.24.2, pygame 2.6.1.

- Game: `pygame` (real-time top-down, easy to run and screen-record).
- Runtime: plain Python module.
- Judgments: TypeSafe Python SDK (confirm the package name and calls from
  https://docs.typesafe.ai/sdk/python.md).
- A/B baseline: a small fast LLM as the "LLM-as-judge" arm, via **OpenRouter**
  (OpenAI-compatible, so we use the `openai` SDK with OpenRouter's base URL).
  `BASELINE_MODEL` picks the model. Using a *fast* model is the fair comparison: even
  a fast LLM is slower and pricier than a typed judgment.
- Tracing: W&B Weave.
- Tuning surface: marimo.

If we'd rather demo in a browser later, the game is the only piece that changes —
the runtime, evals, and Weave stay put. Not for this slice.

`requirements.txt`:
```
typesafe-sdk        # the judgments
openai              # baseline arm (LLM-as-judge, via OpenRouter)
weave               # tracing (pulls in wandb)
marimo              # tuning surface (nice-to-have)
pygame              # the game
python-dotenv       # load .env locally
```

---

## 3. Repo layout

```
instinct/
  runtime/                 # shared, game-agnostic — the reusable core
    __init__.py
    judge.py               # choice/noul/score → routes to TypeSafe or baseline
    baseline.py            # LLM-as-judge arm (OpenRouter)
    memory.py              # recall() / distill() — the learning loop
    trace.py               # Weave logging helpers
    config.py              # arm switch, TTLs; reads keys from env only
  games/
    stealth/
      game.py              # pygame loop, world, guards, player, vision, pathing
      state.py             # build guard_state from the world
      judgments.py         # the guard_action Choice + code-side rules
      eval_cases.py        # golden set
  tuning/
    stealth_tuning.py      # marimo notebook (nice-to-have)
  evals/
    run_evals.py           # accuracy + latency + cost + A/B over the golden set
  .env.example             # committed, placeholders only
  .gitignore
  requirements.txt
  README.md
  BUILD.md                 # this doc
```

Keep the hard line: `games/stealth` imports from `runtime` and never reaches inside
it. The runtime knows nothing about guards. That discipline is what lets Turing Tag
reuse the same core, and it's the whole "one runtime" claim.

---

## 4. Secrets and repo hygiene (do this before the first commit)

Keys live in `.env`, which is never committed. Source reads them from the
environment. Nothing else.

`.gitignore`:
```
# secrets / env
.env
.env.*
!.env.example
*.key
secrets/

# python
__pycache__/
*.py[cod]
.venv/
venv/

# tooling caches / local
wandb/
__marimo__/
.DS_Store
*.local
```

`.env.example` (committed, placeholders — no real values):
```
TYPESAFE_API_KEY=your_typesafe_key_here
WANDB_API_KEY=your_wandb_key_here
OPENROUTER_API_KEY=your_openrouter_key_here   # baseline arm (LLM-as-judge)
BASELINE_MODEL=openai/gpt-4o-mini             # any OpenRouter model id
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

Rules for the code:
- `runtime/config.py` reads keys via `os.environ`; if a needed key is missing it
  fails fast with a clear message naming the missing variable. No hardcoded keys,
  ever, not even placeholders, in any `.py`.
- Weave logs game state and decisions only — never the keys.
- First thing on setup: `cp .env.example .env`, fill it in locally, confirm
  `git status` does **not** list `.env`.

---

## 5. The runtime interface (grounded in the real TypeSafe SDK)

Confirmed from docs.typesafe.ai/sdk/python and /primitives:

- `pip install typesafe-sdk`; auth via `TYPESAFE_API_KEY` (from console.typesafe.ai), read from env.
- One call answers one or more questions over ONE shared `state`:

```python
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

async with AsyncTypeSafeClient() as client:
    resp = await client.system_one(
        state={...},                        # named fields
        questions={
            "action": Choice(
                instructions="...the question...",
                criteria={"opt_a": "description", "opt_b": "description"},  # option -> description
            ),
            # more questions over the SAME state run in parallel in this one request
        },
    )
resp.choices["action"].choice          # the pick
resp.choices["action"].probabilities   # distribution over options
resp.choices["action"].confidence      # how peaked the distribution is
# Noul:  resp.nouls[name].noul          -> probability 0..1
# Score: resp.scores[name].score / .probabilities / .confidence / .legend
```

Two facts that shape our design:
- **Batching is per-state.** `system_one` parallelizes multiple questions but over a
  single `state`. Guards each have different state, so **each guard is its own call.**
  (Turing Tag, where every judgment is over the shared game state, is where
  one-request batching pays off.)
- **Concurrency across NPCs = the async client.** Use `AsyncTypeSafeClient` and fire
  each guard's call concurrently (`asyncio.gather`), off the frame loop. That's what
  holds frame rate with many guards, and it's why the async design in section 6 is not
  optional.

Our thin wrapper `runtime/judge.py` gives games a small, arm-agnostic surface plus
timing, caching, Weave logging, and the baseline switch:

```python
# returns {pick, dist, confidence, latency_ms, cost, arm}
await judge.choice(key, state, instructions, criteria)   # one Choice over `state`
await judge.ask(key, state, questions={...})             # multi-question over one state
# noul()/score() are thin wrappers too — build as stubs, wire only choice this slice
```

Wrapper responsibilities: **time** every call (wall-clock latency); **cache** by
`(key, hash(state))` on a short TTL; **log** to Weave; route to TypeSafe or the
baseline by `RUNTIME_ARM`; hold the **memory** store. Cost: read from the response if
the SDK exposes usage, otherwise estimate from pricing — confirm day one.

---

## 6. Stealth spec

**World.** A small grid level: walls, a few rooms, cover tiles, one exit, one
keycard. Guards patrol fixed routes. The player moves and can **throw** an object to
make a noise at a chosen spot. That one verb ("throw") is the whole trick — keep the
verb set minimal.

**Engine owns (plain code, no judgments):** movement, walls, vision cones,
line-of-sight, A* pathing, the noise event when an object lands, win/lose.

**The one judgment — `stealth.guard_action` (Choice):**
```python
# via the wrapper, which calls TypeSafe system_one under the hood (async):
res = await judge.choice(
    key="stealth.guard_action",
    state=guard_state,
    instructions="Given what this guard senses, what should it do right now?",
    criteria={                                   # option -> short description
        "patrol":            "keep the normal patrol route",
        "investigate_noise": "go check the noise or anomaly",
        "chase":             "pursue the player directly",
        "call_backup":       "radio for backup",
        "return_to_post":    "go back to the assigned post",
    },
)
# res.pick == "investigate_noise"
# res.dist == {"investigate_noise":.62,"patrol":.24,"chase":.10,"call_backup":.04,...}
# res.confidence, res.latency_ms, res.cost, res.arm
```

**State the game hands it (`state.py` builds this):**
```python
guard_state = {
    "guard":        {"id": g.id, "alertness": "calm|wary|alert",
                     "last_saw_player_secs": int | None, "post": g.post},
    "just_noticed": [ ... ],   # this tick's anomalies, e.g. "heard a clang to the NE",
                               #                              "a door I closed is open"
    "sightings":    {"player_in_view": bool, "last_seen_desc": str | None},
    "this_player":  memory.recall(player_id),   # learned tricks, e.g. {"tricks": [...]}
    "policy":       "call backup only after a direct sighting",
}
```

**Code-side rules around the judgment (in `judgments.py`):**
- *When to ask.* Only call when `just_noticed` is non-empty or a sighting changed.
  Otherwise run the cheap patrol behavior — no call. Throttle to at most one call per
  guard every ~0.5s.
- *Async, never blocks a frame.* Issue the request; the guard keeps doing its current
  behavior until the answer returns a few ms later, then switches. This matters: it
  means the *reaction delay* is what differs between arms, not the frame rate. With
  the LLM arm the guard reacts ~1s late — which is exactly why the trick still works
  against it. That's the A/B, shown on screen.
- *Threshold / hysteresis.* `pick = argmax(dist)`; if the top probability < 0.4, keep
  the current behavior (no twitchy flip-flopping).
- *Hard overrides win (engine rules, no judgment).* `player_in_view and
  alertness=="alert"` → force `chase`. `radio_broken` → drop `call_backup` from
  criteria before asking.

**Learning across attempts (`memory.distill`, runs at attempt end, offline):**
- On a failed attempt, summarize what the player did into `this_player.tricks`,
  e.g. `"fake distraction via thrown object"`.
- Next attempt, `memory.recall` injects that into `guard_state.this_player`, so the
  same clang yields a lower `investigate_noise` probability. The distribution shift is
  the demo — no model retraining, just richer state.

**The demo moment (build toward this):**
1. Attempt 1 — throw a rock to the NE. Guard investigates, you slip past.
2. A few attempts later — same rock. Guard now weighs "this player fakes
   distractions," holds position / calls it in. The trick fails; the `dist` on screen
   shows `investigate_noise` dropped.
3. Flip `RUNTIME_ARM` to the LLM baseline — the guard reacts ~1s late and the trick
   works again, at higher cost per call. Point made.

---

## 7. Weave instrumentation

Log on every `judge.*` call (handled in `runtime/trace.py`, so games get it for free):
- `key`, a short state summary, `criteria`, `pick`, full `dist`, `latency_ms`, `cost`, `arm`.
Log once per attempt:
- did the player reach the exit, did the active trick work, number of judgments, attempt index.

Charts to build from this:
- **Guard "fooled rate" across attempts** — should fall as guards learn (the headline).
- **Latency p50/p95 by arm** — TypeSafe vs LLM.
- **Cost per attempt by arm.**
- **Same-scenario A/B** — one seeded attempt through both arms, side by side.

Build these core charts ourselves so the main demo never depends on a preview tool.
Structure the runs so they're easy to analyze later: one W&B run per session/attempt,
consistent metric names, and the arm tagged on every judgment.

### ARIA — best-use-of-ARIA prize track (additive, not on the critical path)

CoreWeave ARIA is an autonomous research agent inside W&B (public preview, built on
Weave) that reads runs and traces at scale, forms hypotheses, builds visualizations
and reports, and recommends the next iteration. Our runtime produces exactly its kind
of input — thousands of judgments across two arms and many attempts — so this is a
natural fit, and since we're already logging to Weave, the extra cost to qualify is low.

Uses, strongest first:
- **The meta-loop (lead with this).** ARIA is an agent that researches agents. Point it
  at our agent loop and have it surface which judgments are weak / slow / ambiguous and
  **recommend tunings**. That's our learning loop automated — an agent improving our
  agent — which is squarely on the agent-loops theme.
- **The A/B, written for us.** ARIA generates the TypeSafe-vs-LLM comparison (latency,
  cost, accuracy) as panels and a report instead of us hand-building it.
- **Failure-mode discovery.** It scans the judgments and points at where the guard
  decides poorly.
- **Learning-curve tracking.** It tracks the fooled-rate trend across attempts.

Rules of engagement:
- Confirm on day one that hackathon participants have ARIA access.
- Keep the core A/B and charts hand-built (above). ARIA is the *showcase* layer
  ("and here's an agent that analyzed all of this on its own and recommended these
  changes"), never the thing the main demo relies on.
- Prerequisite is good Weave logging, which we're doing anyway — so treat ARIA as a
  payoff we get once the traces are rich, not separate upfront work.

---

## 8. Evals harness (`evals/run_evals.py`)

Golden cases live in `games/stealth/eval_cases.py` as `(state, expected_pick)` pairs.
Seed set (grow to ~12–15):

| state | expected |
|---|---|
| clang NE, no sighting, calm, `this_player` empty | `investigate_noise` |
| clang NE, `tricks=["fake distraction via thrown object"]`, calm | `patrol` / `return_to_post` |
| saw player once, lost them, wary | `investigate_noise` (last seen), not `call_backup` |
| player_in_view, alert | `chase` |
| nothing noticed, calm | `patrol` |

`run_evals.py` runs the set through both arms and prints:
- accuracy per arm (share matching `expected`),
- latency p50/p95 per arm,
- cost per arm,
- a small A/B table.
Then a **learning-curve** mode replays the same scenarios with `tricks` accumulating,
so accuracy on "should not be fooled" cases climbs. Same golden set, three proofs:
it's smart, it's cheaper/faster than the LLM, it improves.

---

## 9. marimo tuning (nice-to-have)

`tuning/stealth_tuning.py` — a reactive notebook where you edit the judgment's
criteria, the policy string, or the thresholds, and watch a canned scenario's
distribution (or a live guard) change immediately. This is the "authoring surface"
part of the story and it's game-agnostic — it operates on judgments, not guards.

---

## 10. Build order

Vertical slice, in order. Each step is runnable before the next.

1. **Repo + hygiene.** Layout, `.gitignore`, `.env.example`, `requirements.txt`,
   `config.py` reading keys from env. Confirm `.env` is ignored.
2. **Runtime `choice` → TypeSafe.** Real call, real typed answer, returned with
   latency/cost. `noul`/`score` as stubs.
3. **Stealth playable, guards on plain rules.** Level, player, throw, guard patrol +
   vision + chase-on-sight. No judgments yet — just a working game.
4. **Swap guard decisions to `judge.choice`.** Build `guard_state`, wire the async
   call, the when-to-ask gate, threshold, and overrides.
5. **Weave logging.** Every judgment + per-attempt outcome. See the first charts.
6. **Memory / learning.** `recall` before the judgment, `distill` at attempt end.
   Get the trick-stops-working behavior on screen.
7. **Baseline arm + arm switch.** A fast OpenRouter model as LLM-as-judge behind the
   same interface; `RUNTIME_ARM` flag.
8. **Evals harness.** Golden set, accuracy/latency/cost/A-B, learning-curve replay.
9. **(If time) marimo tuning notebook.**

Rough split for two people: one on 3 (game) while the other does 1–2 then 5–7
(runtime, Weave, baseline); converge at 4; share 8.

---

## 11. Risks / cut list

- **TypeSafe SDK** — package/auth/call shape are pinned (section 5). Still open: whether
  the response exposes per-call cost/usage, and the rate limits. Check both day one.
- **Cut order if behind:** marimo notebook → learning-curve replay mode (keep static
  accuracy + A/B) → memory/learning (keep the static "smart decision" + A/B story).
- **Keep the verb set tiny.** One meaningful player verb (throw). Resist adding
  stealth mechanics that don't feed the judgment.
- **Async discipline.** If a judgment ever blocks the frame, the game stutters and the
  A/B story breaks. The call must be off the render path from step 4.
