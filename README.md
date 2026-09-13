# Instinct

A game-AI runtime where NPC decisions are fast typed judgments (TypeSafe), instead of
brittle scripts or slow LLM calls — smart NPCs at the speed and cost of dumb ones.

This repo is the **Stealth slice**: a small, local stealth game whose guards decide
what to do via a TypeSafe Choice judgment, running through a reusable runtime module.
See `BUILD.md` for the full plan and build order.

## Setup

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in your keys — never commit .env
```

## Run (once built)

```
python -m games.stealth.game      # the game
python -m evals.run_evals         # accuracy + A/B vs the LLM baseline
```

## Layout

- `runtime/` — shared, game-agnostic: judgments, baseline arm, memory, tracing, config
- `games/stealth/` — the game and its judgment
- `evals/` — the golden set and the A/B harness
- `tuning/` — marimo tuning notebook (nice-to-have)

Keys live in `.env` (gitignored). Nothing here gets deployed; it runs locally for play
and for recording the demo.
