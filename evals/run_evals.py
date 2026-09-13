"""Run the golden set through both arms and report.

Prints accuracy per arm, latency p50/p95, cost, and a small A/B table. A --learning
mode replays the cases with `this_player.tricks` accumulating so the "should not be
fooled" accuracy climbs. See BUILD.md section 8. Build step 8.
"""


def main() -> None:
    raise NotImplementedError("Build step 8: accuracy + latency + cost + A/B harness.")


if __name__ == "__main__":
    main()
