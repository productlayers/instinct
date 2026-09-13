"""Side-by-side A/B demo, scripted for recording: Instinct NPCs vs LLM NPCs.

Same scene on both sides. A scripted intruder (YOU) walks toward the exit past a guard's
post. When the intruder gets close, the guard makes one decision through the runtime and
moves to cut them off. The only difference between the two sides is which engine answers:
Instinct (typed judgment, left) or an LLM per decision (right).

The outcome falls out of the real reaction time. The guard that decides fast reaches the
chokepoint in time and CATCHES the intruder; the slow one arrives late and the intruder
ESCAPES. Nothing is faked: both sides make real calls; the geometry just turns the latency
gap into a caught-vs-escaped result you can see.

Deterministic and self-running so it records cleanly. Press SPACE to replay, Esc to quit.
Run: `python -m games.stealth.demo`   Headless outcome check: add `--selftest`.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
import time
from dataclasses import dataclass, field

import pygame

from runtime import judge, trace
from games.stealth.judgments import GUARD_ACTIONS
from games.stealth.game import DecisionService

# --- arena ----------------------------------------------------------------
DTILE = 34
LEVEL = [
    "################",
    "#..............#",
    "#..............#",
    "#..............#",
    "#..............#",
    "#..............#",
    "#..............#",
    "#..............#",
    "#..............#",
    "#..............#",
    "################",
]
DCOLS, DROWS = len(LEVEL[0]), len(LEVEL)
ARENA_W, ARENA_H = DCOLS * DTILE, DROWS * DTILE
HEADER_H, FOOTER_H, GAP = 44, 92, 26
W = ARENA_W * 2 + GAP
H = HEADER_H + ARENA_H + FOOTER_H

# scenario geometry
CORRIDOR_ROW = 8            # the row the intruder walks
BLOCK_COL = 8              # the chokepoint column the guard must reach
POST_ROW = 2               # the guard starts here, well above the corridor
EXIT_COL = DCOLS - 2       # reaching this column = escaped
PLAYER_SPEED = 1.7
GUARD_SPEED = 3.0
CATCH_RANGE = 0.85 * DTILE

# Tie the trigger distance to the geometry so the catch/escape boundary sits at
# ~catch_slack frames of reaction (~0.28s), right between a typed reaction (~0.13s,
# catches) and an LLM reaction (~0.45s, misses). Nothing is faked; only the geometry
# is tuned so the real latency gap decides the outcome.
_descent_px = (CORRIDOR_ROW - POST_ROW) * DTILE
DETECT_AHEAD = _descent_px * PLAYER_SPEED / GUARD_SPEED

INSTRUCTIONS = (
    "You can see an intruder crossing your post and heading straight for the exit. "
    "Decide what this guard does right now."
)
REACT_PICKS = {"chase", "investigate_noise", "call_backup"}

C_BG = (10, 12, 16)
C_FLOOR_A, C_FLOOR_B = (26, 30, 38), (23, 27, 34)
C_WALL, C_WALL_TOP = (15, 17, 22), (44, 50, 62)
C_INK, C_MUTE = (222, 228, 236), (132, 142, 156)
C_INSTINCT, C_LLM = (54, 211, 192), (232, 168, 74)
C_PLAYER = (86, 166, 255)
C_GOOD, C_BAD = (70, 210, 140), (232, 96, 84)


def center_of(tx, ty):
    return tx * DTILE + DTILE / 2, ty * DTILE + DTILE / 2


@dataclass
class Side:
    name: str
    arm: str
    color: tuple
    px: float
    py: float
    gx: float
    gy: float
    facing: float = math.pi / 2
    requested: bool = False
    reacting: bool = False
    react_ms: float | None = None
    pick: str | None = None
    outcome: str | None = None       # None | "CAUGHT" | "ESCAPED"
    min_sep: float = 1e9


def make_side(name, arm, color):
    px, py = center_of(1, CORRIDOR_ROW)
    gx, gy = center_of(BLOCK_COL, POST_ROW)
    return Side(name, arm, color, px, py, gx, gy)


def scenario_state(s: Side):
    return {
        "guard": {"alertness": "alert", "post": f"guarding the corridor at column {BLOCK_COL}"},
        "just_noticed": ["an intruder is in plain sight, crossing the post toward the exit"],
        "sightings": {"player_in_view": True, "last_seen_desc": "in the corridor, moving to the exit"},
        "this_player": {},
        "policy": "stop any intruder you can see before they reach the exit",
    }


def update_side(s: Side, service, gid):
    if s.outcome is not None:
        return
    block_x = BLOCK_COL * DTILE + DTILE / 2

    # intruder walks steadily toward the exit
    s.px += PLAYER_SPEED

    # trigger the one decisive decision when the intruder gets close
    if not s.requested and s.px >= block_x - DETECT_AHEAD:
        service.request(gid, scenario_state(s), INSTRUCTIONS, GUARD_ACTIONS, arm=s.arm)
        s.requested = True

    res, _ = service.take(gid)
    if res is not None and s.react_ms is None:
        s.react_ms = res.latency_ms
        s.pick = res.pick
        s.reacting = res.pick in REACT_PICKS if res.pick else True

    # once the guard has reacted, it moves to cut off the chokepoint
    if s.reacting:
        tx, ty = block_x, CORRIDOR_ROW * DTILE + DTILE / 2
        dx, dy = tx - s.gx, ty - s.gy
        d = math.hypot(dx, dy)
        if d > 1:
            s.facing = math.atan2(dy, dx)
            s.gx += min(GUARD_SPEED, d) * dx / d
            s.gy += min(GUARD_SPEED, d) * dy / d

    # outcomes
    sep = math.hypot(s.px - s.gx, s.py - s.gy)
    if s.reacting:
        s.min_sep = min(s.min_sep, sep)
    if sep <= CATCH_RANGE and s.reacting:
        s.outcome = "CAUGHT"
    elif s.px >= EXIT_COL * DTILE:
        s.outcome = "ESCAPED"


# --- rendering ------------------------------------------------------------
def draw_side(screen, fonts, s: Side, ox, tick):
    oy = HEADER_H
    for ty in range(DROWS):
        for tx in range(DCOLS):
            r = pygame.Rect(ox + tx * DTILE, oy + ty * DTILE, DTILE, DTILE)
            wall = LEVEL[ty][tx] == "#"
            if wall:
                pygame.draw.rect(screen, C_WALL, r)
                pygame.draw.rect(screen, C_WALL_TOP, (r.x, r.y, DTILE, 3))
            else:
                pygame.draw.rect(screen, C_FLOOR_A if (tx + ty) % 2 else C_FLOOR_B, r)

    # exit marker
    ex, ey = ox + EXIT_COL * DTILE - DTILE, oy + CORRIDOR_ROW * DTILE
    pygame.draw.rect(screen, C_GOOD, (ex + 6, ey + 6, DTILE - 12, DTILE - 12), border_radius=6)
    screen.blit(fonts["xs"].render("EXIT", True, C_GOOD), (ex - 2, ey - 14))

    # guard
    gcol = s.color if s.reacting else C_MUTE
    pygame.draw.circle(screen, gcol, (int(ox + s.gx), int(oy + s.gy)), int(DTILE * 0.32))
    tip = (ox + s.gx + math.cos(s.facing) * DTILE * 0.42, oy + s.gy + math.sin(s.facing) * DTILE * 0.42)
    pygame.draw.line(screen, C_INK, (ox + s.gx, oy + s.gy), tip, 3)
    if s.requested and s.react_ms is None:
        dots = "." * (1 + (tick // 10) % 3)
        screen.blit(fonts["xs"].render("deciding" + dots, True, C_INK), (ox + s.gx - 26, oy + s.gy - DTILE * 0.7))

    # intruder (YOU)
    pxi, pyi = int(ox + s.px), int(oy + s.py)
    pygame.draw.circle(screen, (255, 255, 255), (pxi, pyi), int(DTILE * 0.34))
    pygame.draw.circle(screen, C_PLAYER, (pxi, pyi), int(DTILE * 0.27))
    screen.blit(fonts["xs"].render("YOU", True, (255, 255, 255)), (pxi - 12, pyi - int(DTILE * 0.75)))


def draw_footer(screen, fonts, s: Side, ox):
    y = HEADER_H + ARENA_H + 12
    rt = f"{s.react_ms:.0f} ms" if s.react_ms is not None else "deciding..."
    screen.blit(fonts["xs"].render("reaction time", True, C_MUTE), (ox + 16, y))
    screen.blit(fonts["big"].render(rt, True, s.color), (ox + 16, y + 13))
    if s.outcome:
        col = C_BAD if s.outcome == "ESCAPED" else C_GOOD
        label = "INTRUDER ESCAPED" if s.outcome == "ESCAPED" else "INTRUDER CAUGHT"
        surf = fonts["out"].render(label, True, col)
        screen.blit(surf, (ox + ARENA_W - surf.get_width() - 16, y + 6))


def build_fonts():
    return {
        "xs": pygame.font.SysFont("menlo,monospace", 12),
        "title": pygame.font.SysFont("helvetica,arial", 20, bold=True),
        "big": pygame.font.SysFont("menlo,monospace", 20, bold=True),
        "out": pygame.font.SysFont("helvetica,arial", 20, bold=True),
    }


def reset_sides():
    return make_side("Instinct", "typesafe", C_INSTINCT), make_side("LLM NPCs", "baseline", C_LLM)


def run(headless=False, frames=0):
    import os
    if headless:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    else:
        proj = trace.init()
        if proj:
            print(f"[weave] tracing to '{proj}'")
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Instinct vs LLM NPCs")
    fonts = build_fonts()
    clock = pygame.time.Clock()
    service = DecisionService()
    left, right = reset_sides()

    # warm up both arms so the decisive call reflects steady-state latency, not cold start
    for wid, warm_arm in (("warmL", "typesafe"), ("warmR", "baseline")):
        service.request(wid, scenario_state(left), INSTRUCTIONS, GUARD_ACTIONS, arm=warm_arm)
    warm = {}
    for _ in range(500):
        for wid in ("warmL", "warmR"):
            r, _ = service.take(wid)
            if r:
                warm[wid] = r.latency_ms
        if len(warm) == 2:
            break
        if not headless:
            screen.fill(C_BG)
            msg = fonts["title"].render("Warming up both engines...", True, C_MUTE)
            screen.blit(msg, (W // 2 - msg.get_width() // 2, H // 2 - 12))
            pygame.display.flip()
        time.sleep(0.02)
    if headless:
        print(f"warm latencies: typed={warm.get('warmL') and round(warm['warmL'])} "
              f"llm={warm.get('warmR') and round(warm['warmR'])}")

    tick, running, started = 0, True, headless
    while running:
        if headless and (tick >= frames or (left.outcome and right.outcome)):
            break
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                running = False
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                left, right = reset_sides()
                tick, started = 0, True
        if started:
            update_side(left, service, "L")
            update_side(right, service, "R")
        screen.fill(C_BG)
        pygame.draw.line(screen, C_WALL_TOP, (ARENA_W + GAP // 2, 0), (ARENA_W + GAP // 2, H))
        for s, ox in ((left, 0), (right, ARENA_W + GAP)):
            screen.blit(fonts["title"].render(s.name, True, s.color), (ox + 14, 10))
            tag = "typed judgment" if s.arm == "typesafe" else "an LLM per decision"
            screen.blit(fonts["xs"].render(tag, True, C_MUTE), (ox + 16 + fonts["title"].size(s.name)[0], 18))
            draw_side(screen, fonts, s, ox, tick)
            draw_footer(screen, fonts, s, ox)
        if not started:
            hint = fonts["title"].render("press SPACE to run", True, C_INK)
            screen.blit(hint, (W // 2 - hint.get_width() // 2, H - 38))
        if not headless:
            pygame.display.flip()
        clock.tick(60)   # 60 fps in both modes so timing (and the outcome) matches
        tick += 1
    service.shutdown()
    pygame.quit()
    if headless:
        for s in (left, right):
            print(f"  {s.name:9} {s.outcome:8} react={s.react_ms and round(s.react_ms)}ms "
                  f"pick={s.pick} reacting={s.reacting} min_sep={round(s.min_sep)}px (catch<{round(CATCH_RANGE)})")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    raise SystemExit(run(headless=args.selftest, frames=600))
