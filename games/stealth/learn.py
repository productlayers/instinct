"""The learning demo: one NPC learns the player's trick in one shot, the other never does.

The player runs the SAME trick every round: throw an object to make a noise to the side,
then slip through the door while the guard goes to check it. Both guards decide through
the same `instinct.Brain`. The only difference is that the left side calls `brain.learn()`
after it gets fooled, and the right side never does:

  Left  (learns the player)  falls for the trick once, then holds the door.
  Right (no memory)          falls for the same trick every round.

The game has no AI code of its own. It calls brain.request() when the distraction lands,
brain.poll() each frame until the decision arrives, and brain.learn() after an escape.

Run: `python -m games.stealth.learn`   Headless check: add `--selftest`.
  --memory FILE   keep what the guard learned in a SQLite file, so it survives a restart
  --timeout S     Jev timeout in seconds; set it tiny to watch the fallback kick in
SPACE replays from scratch (and clears the learned lesson). Esc quits.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass, field

import pygame

from runtime import config, trace  # config loads the repo .env (TYPESAFE_API_KEY)
from instinct import Brain
from games.stealth.judgments import GUARD_ACTIONS

# --- layout ---------------------------------------------------------------
ARENA_W, ARENA_H = 470, 300
HEADER_H, PANEL_H, GAP = 44, 150, 26
W = ARENA_W * 2 + GAP
H = HEADER_H + ARENA_H + PANEL_H

DOOR_X = ARENA_W * 0.56
CORRIDOR_Y = ARENA_H * 0.52
START_X = 26
EXIT_X = ARENA_W - 26
THROW_X = DOOR_X - 150
DISTRACT = (DOOR_X - 30, CORRIDOR_Y - 96)
POST = (DOOR_X + 30, CORRIDOR_Y)
DOORPOS = (DOOR_X, CORRIDOR_Y)
PLAYER_SPEED = 1.9
GUARD_SPEED = 2.6
BLOCK_RANGE = 30
MAX_ROUNDS = 6
TRICK = "throws objects to make noise elsewhere and slip past while the guard investigates"
NOISE_TTL = 80

C_BG = (10, 12, 16)
C_FLOOR_A, C_FLOOR_B = (26, 30, 38), (23, 27, 34)
C_WALL, C_WALL_TOP = (15, 17, 22), (44, 50, 62)
C_INK, C_MUTE = (222, 228, 236), (132, 142, 156)
C_INSTINCT, C_STATIC = (54, 211, 192), (232, 168, 74)
C_PLAYER = (86, 166, 255)
C_NOISE = (236, 238, 242)
C_GOOD, C_BAD = (70, 210, 140), (232, 96, 84)
C_BAR_BG = (30, 35, 44)


INSTRUCTIONS = (
    "Decide what this guard does right now. Weigh everything in the state, including "
    "this_player's lessons: if what the guard just noticed matches a tactic this player "
    "is known to use to bait guards away, do not fall for it."
)
FALLBACK = "return_to_post"

# What the guard senses when the distraction lands. Brain adds what it has learned
# about the player (this_player.lessons) before asking Jev.
SITUATION = {
    "guard": {"alertness": "calm", "last_saw_player_secs": None},
    "just_noticed": ["heard a clang to the side", "a door I closed earlier is open"],
    "sightings": {"player_in_view": False, "last_seen_desc": None},
    "policy": "call backup only after a direct sighting",
}


@dataclass
class Side:
    name: str
    color: tuple
    pid: str
    learns: bool
    px: float = START_X
    py: float = CORRIDOR_Y
    gx: float = POST[0]
    gy: float = POST[1]
    requested: bool = False
    decided: bool = False
    invest: float = 0.0
    pick: str | None = None
    fooled: bool | None = None
    guard_target: tuple | None = None
    outcome: str | None = None
    fooled_count: int = 0
    lessons: list = field(default_factory=list)
    noise_ttl: int = 0
    note: str = ""          # how the last decision was made, shown in the panel


def reset_round(s: Side):
    s.px, s.py = START_X, CORRIDOR_Y
    s.gx, s.gy = POST
    s.requested = s.decided = False
    s.invest, s.pick, s.fooled = 0.0, None, None
    s.guard_target, s.outcome, s.noise_ttl = None, None, 0
    s.note = ""


def update_side(s: Side, brain: Brain):
    if s.outcome is not None:
        if s.noise_ttl > 0:
            s.noise_ttl -= 1
        return

    s.px += PLAYER_SPEED

    if not s.requested and s.px >= THROW_X:
        s.noise_ttl = NOISE_TTL
        brain.request(s.pid, player=s.pid, situation=SITUATION)
        s.requested = True

    if s.noise_ttl > 0:
        s.noise_ttl -= 1

    if not s.decided:
        d = brain.poll(s.pid)
        if d is not None:
            s.decided = True
            s.pick = d.action
            s.invest = float(d.probabilities.get("investigate_noise", 0.0))
            s.fooled = d.action == "investigate_noise"
            s.guard_target = DISTRACT if s.fooled else DOORPOS
            s.note = (f"decided by Jev in {d.latency_ms:.0f} ms" if not d.fell_back
                      else f"fallback ({d.reason.replace('_', ' ')}): {d.action}")

    if s.guard_target is not None:
        tx, ty = s.guard_target
        dx, dy = tx - s.gx, ty - s.gy
        d = math.hypot(dx, dy)
        if d > 1:
            s.gx += min(GUARD_SPEED, d) * dx / d
            s.gy += min(GUARD_SPEED, d) * dy / d

    # resolve when the intruder reaches the door
    if s.px >= DOOR_X:
        blocked = math.hypot(s.gx - DOORPOS[0], s.gy - DOORPOS[1]) <= BLOCK_RANGE
        if blocked:
            s.outcome = "CAUGHT"
        elif s.px >= EXIT_X:
            s.outcome = "ESCAPED"
    if s.outcome == "ESCAPED" and s.fooled:
        s.fooled_count += 1
        if s.learns and not s.lessons:
            # Distill the lesson from what actually happened this round (the traced
            # decision + outcome), not a hardcoded trick. The guard chose to leave and
            # investigate a side-noise, and the intruder used that opening.
            obs = ("last time, this guard left its post to investigate a noise off to the "
                   "side, and the intruder used that opening to slip through the door and escape")
            brain.learn(s.pid, obs)
            s.lessons.append(obs)


# --- rendering ------------------------------------------------------------
def draw_arena(screen, fonts, s: Side, ox):
    oy = HEADER_H
    pygame.draw.rect(screen, C_FLOOR_A, (ox, oy, ARENA_W, ARENA_H))
    # the wall with a door gap
    wx = int(ox + DOOR_X)
    pygame.draw.rect(screen, C_WALL, (wx - 6, oy, 12, ARENA_H))
    pygame.draw.rect(screen, C_FLOOR_B, (wx - 6, int(oy + CORRIDOR_Y - 26), 12, 52))  # doorway gap
    # exit
    pygame.draw.rect(screen, C_GOOD, (int(ox + EXIT_X - 10), int(oy + CORRIDOR_Y - 14), 20, 28), border_radius=5)
    screen.blit(fonts["xs"].render("EXIT", True, C_GOOD), (int(ox + EXIT_X - 14), int(oy + CORRIDOR_Y - 32)))

    # distraction ping
    if s.noise_ttl > 0:
        rad = int((NOISE_TTL - s.noise_ttl) * 0.5) + 4
        al = max(0, int(210 * s.noise_ttl / NOISE_TTL))
        ring = pygame.Surface((rad * 2 + 4, rad * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(ring, (*C_NOISE, al), (rad + 2, rad + 2), rad, 2)
        screen.blit(ring, (int(ox + DISTRACT[0] - rad - 2), int(oy + DISTRACT[1] - rad - 2)))

    # guard
    pygame.draw.circle(screen, s.color, (int(ox + s.gx), int(oy + s.gy)), 11)
    # intruder
    pxi, pyi = int(ox + s.px), int(oy + s.py)
    pygame.draw.circle(screen, (255, 255, 255), (pxi, pyi), 9)
    pygame.draw.circle(screen, C_PLAYER, (pxi, pyi), 7)
    screen.blit(fonts["xs"].render("YOU", True, (255, 255, 255)), (pxi - 11, pyi - 22))

    if s.outcome:
        col = C_BAD if s.outcome == "ESCAPED" else C_GOOD
        lab = "SLIPPED PAST" if s.outcome == "ESCAPED" else "CAUGHT"
        surf = fonts["out"].render(lab, True, col)
        screen.blit(surf, (int(ox + ARENA_W / 2 - surf.get_width() / 2), oy + 10))


def draw_panel(screen, fonts, s: Side, ox, round_no):
    y = HEADER_H + ARENA_H + 12
    # investigate chance bar
    screen.blit(fonts["xs"].render("chance it takes the bait", True, C_MUTE), (ox + 16, y))
    bx, bw = ox + 16, ARENA_W - 180
    pygame.draw.rect(screen, C_BAR_BG, (bx, y + 18, bw, 12), border_radius=4)
    col = C_BAD if s.invest > 0.5 else C_GOOD
    pygame.draw.rect(screen, col, (bx, y + 18, max(2, int(bw * s.invest)), 12), border_radius=4)
    screen.blit(fonts["m"].render(f"{s.invest*100:.0f}%", True, col), (bx + bw + 8, y + 15))
    # times fooled
    screen.blit(fonts["xs"].render("times fooled", True, C_MUTE), (ox + ARENA_W - 120, y))
    screen.blit(fonts["huge"].render(str(s.fooled_count), True, s.color), (ox + ARENA_W - 120, y + 12))
    # lessons
    ly = y + 46
    screen.blit(fonts["xs"].render("lessons learned", True, C_MUTE), (ox + 16, ly))
    if s.lessons:
        for i, _ in enumerate(s.lessons):
            screen.blit(fonts["xs"].render("• don't chase a side-noise from this player", True, C_INSTINCT),
                        (ox + 16, ly + 16 + i * 15))
    else:
        screen.blit(fonts["xs"].render("(none, no memory of past rounds)", True, C_MUTE), (ox + 16, ly + 16))
    if s.note:
        col = C_BAD if s.note.startswith("fallback") else C_MUTE
        screen.blit(fonts["xs"].render(s.note, True, col), (ox + 16, ly + 50))


def build_fonts():
    return {
        "xs": pygame.font.SysFont("menlo,monospace", 12),
        "m": pygame.font.SysFont("menlo,monospace", 15, bold=True),
        "title": pygame.font.SysFont("helvetica,arial", 20, bold=True),
        "out": pygame.font.SysFont("helvetica,arial", 18, bold=True),
        "huge": pygame.font.SysFont("menlo,monospace", 30, bold=True),
    }


def run(headless=False, frames=0, capture=None, record_gif=None, memory_path=":memory:", timeout_s=1.0):
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
    pygame.display.set_caption("Instinct learns the player. The other NPC never does.")
    fonts = build_fonts()
    clock = pygame.time.Clock()
    brain = Brain(GUARD_ACTIONS, instructions=INSTRUCTIONS, fallback=FALLBACK,
                  memory=memory_path, timeout_s=timeout_s, trace=trace.is_on())

    def fresh(wipe=False):
        if wipe:
            brain.forget("instinct_p")
        brain.forget("static_p")  # the no-memory side never keeps anything
        left = Side("Learns the player", C_INSTINCT, "instinct_p", True)
        left.lessons = brain.lessons("instinct_p")  # already learned, e.g. before a restart
        return left, Side("No memory", C_STATIC, "static_p", False)

    left, right = fresh()
    round_no = 1
    hold = 0
    tick, running = 0, True
    while running:
        if headless and (tick >= frames or (round_no > MAX_ROUNDS)):
            break
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                running = False
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                left, right = fresh(wipe=True)
                round_no, hold = 1, 0

        if round_no <= MAX_ROUNDS:
            update_side(left, brain)
            update_side(right, brain)
            if left.outcome and right.outcome:
                hold += 1
                if hold > 70:
                    round_no += 1
                    hold = 0
                    if round_no <= MAX_ROUNDS:
                        reset_round(left)
                        reset_round(right)

        screen.fill(C_BG)
        pygame.draw.line(screen, C_WALL_TOP, (ARENA_W + GAP // 2, 0), (ARENA_W + GAP // 2, H))
        for s, ox in ((left, 0), (right, ARENA_W + GAP)):
            screen.blit(fonts["title"].render(s.name, True, s.color), (ox + 14, 8))
            tag = "remembers what fooled it" if s.learns else "same Brain, never calls learn()"
            screen.blit(fonts["xs"].render(tag, True, C_MUTE), (ox + 16 + fonts["title"].size(s.name)[0], 16))
            draw_arena(screen, fonts, s, ox)
            draw_panel(screen, fonts, s, ox, round_no)
        rlabel = f"round {min(round_no, MAX_ROUNDS)} / {MAX_ROUNDS}" if round_no <= MAX_ROUNDS else "done, SPACE to replay"
        rl = fonts["m"].render(rlabel, True, C_INK)
        screen.blit(rl, (W // 2 - rl.get_width() // 2, 12))

        if capture and round_no == 3 and left.outcome and right.outcome and hold == 20:
            pygame.image.save(screen, capture)
            print(f"saved frame to {capture}")
            running = False
        if record_gif is not None and round_no <= 3 and tick % 3 == 0:
            from PIL import Image
            raw = pygame.image.tostring(screen, "RGB")
            img = Image.frombytes("RGB", (W, H), raw).resize((580, int(580 * H / W)))
            record_gif.append(img)
        if record_gif is not None and round_no >= 4:
            running = False
        if not headless:
            pygame.display.flip()
        clock.tick(60)
        tick += 1
    stats = brain.stats()
    brain.close()
    pygame.quit()
    if headless:
        print(f"after {min(round_no-1, MAX_ROUNDS)} rounds -> times fooled: "
              f"learns={left.fooled_count}, no-memory={right.fooled_count}  "
              f"(invest now {left.invest:.2f} vs {right.invest:.2f})  brain: {stats}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--capture", default=None)
    ap.add_argument("--record-gif", default=None)
    ap.add_argument("--memory", default=":memory:", help="SQLite file so learning survives restarts")
    ap.add_argument("--timeout", type=float, default=1.0, help="Jev timeout in seconds")
    args = ap.parse_args()
    opts = dict(memory_path=args.memory, timeout_s=args.timeout)
    if args.capture:
        raise SystemExit(run(headless=True, frames=4000, capture=args.capture, **opts))
    if args.record_gif:
        from PIL import Image
        frames_list = []
        run(headless=True, frames=6000, record_gif=frames_list, **opts)
        if frames_list:
            frames_list[0].save(args.record_gif, save_all=True, append_images=frames_list[1:],
                                duration=100, loop=0, optimize=True)
            print(f"saved gif to {args.record_gif} ({len(frames_list)} frames)")
        raise SystemExit(0)
    raise SystemExit(run(headless=args.selftest, frames=4000, **opts))
