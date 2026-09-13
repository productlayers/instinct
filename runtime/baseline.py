"""LLM-as-judge arm: answers the same judgments with a fast small model via
W&B Inference (OpenAI-compatible), returning structured output. Used only for the A/B.

Use the `openai` SDK pointed at W&B Inference (auth is the W&B API key):
    from openai import OpenAI
    client = OpenAI(base_url=config.WANDB_INFERENCE_BASE_URL,
                    api_key=config.require("WANDB_API_KEY"),
                    project=config.WANDB_INFERENCE_PROJECT or None)
    client.chat.completions.create(model=config.BASELINE_MODEL, ...)

See BUILD.md sections 5-6. Build step 7.
"""


async def choice(state, instructions, criteria) -> dict:
    """TODO (step 7): prompt the baseline model to pick one option and give a
    probability per option as JSON; parse it; count parse failures as a data point.
    Return the same shape as runtime.judge.Result.
    """
    raise NotImplementedError("Build step 7: LLM-as-judge baseline (W&B Inference).")
