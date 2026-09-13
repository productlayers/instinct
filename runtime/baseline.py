"""LLM-as-judge arm: answers the same judgments with a fast small model via
OpenRouter (OpenAI-compatible), returning structured output. Used only for the A/B.

Use the `openai` SDK pointed at OpenRouter:
    from openai import OpenAI
    client = OpenAI(base_url=config.OPENROUTER_BASE_URL,
                    api_key=config.require("OPENROUTER_API_KEY"))
    client.chat.completions.create(model=config.BASELINE_MODEL, ...)

See BUILD.md sections 5-6. Build step 7.
"""


async def choice(state, instructions, criteria) -> dict:
    """TODO (step 7): prompt the baseline model to pick one option and give a
    probability per option as JSON; parse it; count parse failures as a data point.
    Return the same shape as runtime.judge.Result.
    """
    raise NotImplementedError("Build step 7: LLM-as-judge baseline (OpenRouter).")
