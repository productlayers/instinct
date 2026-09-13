"""Smoke test: verify the real service paths before we build on them.

Checks TypeSafe (a real judgment), Anthropic Haiku (the baseline arm), Weave
(a real trace), and that marimo imports. Loads keys from .env via python-dotenv.

It NEVER prints key values — only whether each is set, plus non-secret results
(latency, a trace URL, a one-word reply). Each check is isolated so one failure
doesn't hide the others.

Run:  python checks/smoke_test.py
"""
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass  # if python-dotenv isn't installed, env vars may still be set another way

import os

OK, FAIL = "PASS", "FAIL"
results = {}


def key_status(name: str) -> str:
    return "set" if os.environ.get(name) else "MISSING"


def check_env():
    print("Keys (from .env):")
    for k in ("TYPESAFE_API_KEY", "WANDB_API_KEY", "OPENROUTER_API_KEY"):
        print(f"  {k}: {key_status(k)}")
    print()


def check_typesafe():
    name = "TypeSafe judgment"
    try:
        from typesafe_sdk import TypeSafeClient, Choice, Noul
        t0 = time.perf_counter()
        with TypeSafeClient() as client:
            resp = client.system_one(
                state={"document": "I was charged twice. Please fix this ASAP."},
                questions={
                    "billing": Noul(instructions="Is this ticket about billing?"),
                    "tone": Choice(
                        instructions="What is the customer's tone?",
                        criteria={"calm": None, "frustrated": None, "angry": None},
                    ),
                },
            )
        ms = (time.perf_counter() - t0) * 1000
        billing = resp.nouls["billing"].noul
        tone = resp.choices["tone"].choice
        print(f"[{OK}] {name}: billing={billing:.2f}, tone={tone!r}, {ms:.0f} ms")
        # confirm the response also carries a distribution + confidence, as the docs say
        probs = getattr(resp.choices["tone"], "probabilities", None)
        conf = getattr(resp.choices["tone"], "confidence", None)
        print(f"       probabilities present: {probs is not None}, confidence present: {conf is not None}")
        results[name] = True
    except Exception as e:
        print(f"[{FAIL}] {name}: {type(e).__name__}: {e}")
        results[name] = False


def check_openrouter():
    name = "OpenRouter (baseline arm)"
    try:
        from openai import OpenAI
        model = os.environ.get("BASELINE_MODEL", "openai/gpt-4o-mini")
        base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        client = OpenAI(base_url=base_url, api_key=os.environ["OPENROUTER_API_KEY"])
        t0 = time.perf_counter()
        resp = client.chat.completions.create(
            model=model,
            max_tokens=10,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )
        ms = (time.perf_counter() - t0) * 1000
        text = (resp.choices[0].message.content or "").strip()
        print(f"[{OK}] {name}: model={model}, reply={text!r}, {ms:.0f} ms")
        results[name] = True
    except Exception as e:
        print(f"[{FAIL}] {name}: {type(e).__name__}: {e}")
        print("       (if it's a model error, set BASELINE_MODEL in .env to a current OpenRouter id)")
        results[name] = False


def check_weave():
    name = "Weave trace"
    try:
        import weave
        weave.init("instinct-smoke")

        @weave.op
        def ping(x: int) -> int:
            return x + 1

        ping(1)
        print(f"[{OK}] {name}: initialized and logged one op (see the trace URL above)")
        results[name] = True
    except Exception as e:
        print(f"[{FAIL}] {name}: {type(e).__name__}: {e}")
        results[name] = False


def check_marimo():
    name = "marimo (local, no service)"
    try:
        import marimo
        print(f"[{OK}] {name}: import ok, version {marimo.__version__}")
        results[name] = True
    except Exception as e:
        print(f"[{FAIL}] {name}: {type(e).__name__}: {e}")
        results[name] = False


if __name__ == "__main__":
    check_env()
    check_typesafe()
    check_openrouter()
    check_weave()
    check_marimo()
    print("\n=== summary ===")
    for k, v in results.items():
        print(f"  {OK if v else FAIL}: {k}")
    all_ok = all(results.values()) and len(results) == 4
    print("\nall green" if all_ok else "\nsome checks failed — see above")
    raise SystemExit(0 if all_ok else 1)
