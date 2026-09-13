"""Instinct tuning surface (marimo).

A reactive notebook over the same judgment the game uses. Toggle whether the guard has
learned the player's trick, or edit what it just noticed, and watch its real decision and
probability distribution update live. This is the authoring surface: it operates on the
judgment, not on any game internals, so it is game-agnostic.

Run:  marimo edit tuning/stealth_tuning.py
"""
import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    from runtime import config  # importing loads the repo .env (TYPESAFE_API_KEY)
    from typesafe_sdk import TypeSafeClient, Choice
    from games.stealth.judgments import GUARD_ACTIONS, GUARD_INSTRUCTIONS
    return Choice, GUARD_ACTIONS, GUARD_INSTRUCTIONS, TypeSafeClient, mo


@app.cell
def _(mo):
    mo.md(
        """
        # Instinct — tuning surface

        The same typed judgment the guards use. Change the inputs and watch the guard's
        real decision update live. The one toggle that matters: has it **learned** this
        player's trick yet?
        """
    )
    return


@app.cell
def _(mo):
    learned = mo.ui.switch(value=False, label="Guard has learned this player's trick")
    noticed = mo.ui.text(
        value="heard a clang to the side, and a door I closed earlier is open",
        label="What the guard just noticed", full_width=True,
    )
    mo.vstack([learned, noticed])
    return learned, noticed


@app.cell
def _(Choice, GUARD_ACTIONS, GUARD_INSTRUCTIONS, TypeSafeClient, learned, mo, noticed):
    tricks = (
        ["throws objects to make noise elsewhere and slip past while the guard investigates"]
        if learned.value else []
    )
    state = {
        "guard": {"alertness": "calm"},
        "just_noticed": [noticed.value],
        "sightings": {"player_in_view": False},
        "this_player": {"tricks": tricks},
        "policy": "call backup only after a direct sighting",
    }
    with TypeSafeClient() as client:
        resp = client.system_one(
            state=state,
            questions={"action": Choice(instructions=GUARD_INSTRUCTIONS, criteria=GUARD_ACTIONS)},
        )
    ans = resp.choices["action"]
    dist = dict(ans.probabilities)
    invest = dist.get("investigate_noise", 0.0)

    bars = "\n".join(
        f"`{k:<18}` {'█' * int(round(v * 24)):<24} {v:5.0%}"
        for k, v in sorted(dist.items(), key=lambda kv: -kv[1])
    )
    verdict = "takes the bait" if ans.choice == "investigate_noise" else "holds its post"
    mo.md(
        f"### The guard decides: **{ans.choice}** ({verdict})\n\n"
        f"Chance it investigates the side-noise: **{invest:.0%}**\n\n"
        f"```\n{bars}\n```\n"
        f"_Latency {getattr(resp, 'usage', None) and ''}~1 call to TypeSafe per change._"
    )
    return


if __name__ == "__main__":
    app.run()
