"""LLM-as-judge arm: the "how NPCs are built today" comparison.

Answers the same guard decision with a small fast LLM via W&B Inference
(OpenAI-compatible), asking for structured JSON. Used only for the A/B, to show that
the naive LLM-NPC approach is slower, pricier, and occasionally malformed. Returns a
plain dict; runtime.judge builds the Result from it (keeps this module import-light).

Parse failures are counted: when the model returns something we cannot use, that is a
real failure mode of the LLM approach that the typed judgment does not have.
"""
import json

from openai import AsyncOpenAI

from runtime import config

_client: AsyncOpenAI | None = None
parse_failures = 0
calls = 0

_SYS = (
    "You are the decision function for a video-game guard NPC. Given the situation and "
    "the allowed actions, choose exactly ONE action and give a probability (0..1) for "
    "each action. Reply with ONLY a JSON object, no prose: "
    '{"pick": "<action>", "probabilities": {"<action>": <number>, ...}}.'
)


def _client_or_create() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=config.WANDB_INFERENCE_BASE_URL,
            api_key=config.require("WANDB_API_KEY"),
            project=config.WANDB_INFERENCE_PROJECT or None,
        )
    return _client


def _parse(text, opts):
    try:
        s = text[text.index("{"): text.rindex("}") + 1]
        d = json.loads(s)
        probs = d.get("probabilities") or {}
        dist = {o: float(probs.get(o, 0.0)) for o in opts}
        pick = d.get("pick")
        if pick not in opts:
            pick = max(dist, key=dist.get) if any(dist.values()) else None
        return pick, dist
    except Exception:
        return None, {o: 0.0 for o in opts}


async def choice(state, instructions, criteria) -> dict:
    global parse_failures, calls
    calls += 1
    opts = list(criteria)
    user = json.dumps({"instructions": instructions, "state": state, "actions": opts})
    client = _client_or_create()
    resp = await client.chat.completions.create(
        model=config.BASELINE_MODEL,
        max_tokens=220,
        temperature=0,
        messages=[{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
    )
    text = resp.choices[0].message.content or ""
    pick, dist = _parse(text, opts)
    failed = pick is None
    if failed:
        parse_failures += 1
        pick = opts[0]
        dist = {o: (1.0 if o == pick else 0.0) for o in opts}
    usage = getattr(resp, "usage", None)
    return {
        "pick": pick,
        "dist": dist,
        "confidence": dist.get(pick),
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "model": config.BASELINE_MODEL,
        "parse_failed": failed,
    }
