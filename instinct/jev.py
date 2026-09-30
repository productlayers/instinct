"""The default decider: one Jev Choice call through the TypeSafe SDK.

A decider is any async callable (state, instructions, actions) -> Verdict. Brain uses
this one unless you pass your own, which is how the tests run without an API key.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Verdict:
    action: str
    probabilities: dict[str, float]
    confidence: float | None = None


class JevDecider:
    def __init__(self):
        self._client = None

    async def __call__(self, state: dict, instructions: str, actions: dict[str, str]) -> Verdict:
        from typesafe_sdk import AsyncTypeSafeClient, Choice

        if self._client is None:
            self._client = AsyncTypeSafeClient()  # reads TYPESAFE_API_KEY
        resp = await self._client.system_one(
            state=state,
            questions={"action": Choice(instructions=instructions, criteria=actions)},
        )
        ans = resp.choices["action"]
        return Verdict(ans.choice, dict(ans.probabilities), ans.confidence)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
