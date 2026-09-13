"""Pygame stealth level: sneak past guards to reach the exit.

Step 4: guards decide what to do with a real TypeSafe judgment, run off the frame
loop so the call never stalls rendering. A guard keeps acting on its current decision
until the new one lands (shown as "deciding..."), then switches. The decision panel on
the right shows each guard's action, the probability distribution, confidence, latency,
and which arm answered, so the judgment is visible and the A/B is legible.

Hard rules stay in code: seeing the player is an instant chase (no judgment). The
judgment handles the ambiguous case, what to do about a noise it just heard.

Controls: WASD / arrows move. Click to throw a distraction. R restart. Esc quit.
Run: `python -m games.stealth.game`   Headless self-test: add `--selftest`.
"""
from __future__ import annotations

import asyncio
import math
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import pygame

from runtime import judge, trace
from games.stealth.state import guard_state
from games.stealth.judgments import GUARD_ACTIONS, GUARD_INSTRUCTIONS, CONFIDENCE_FLOOR

# --- layout ---------------------------------------------------------------
TILE = 40
LEVEL = [
    "####################",
    "#........#.........#",
    "#.P......#.........#",
    "#........#....##...#",
    "#..####..#........E#",
    "#........#....##...#",
    "#....##......###...#",
    "#....##..#.........#",
    "#........#....##...#",
    "#........#....##...#",
    "#..................#",
    "####################",
]
COLS, ROWS = len(LEVEL[0]), len(LEVEL)
GAME_W, GAME_H = COLS * TILE, ROWS * TILE
PANEL_W = 320
BAR_H = 34
W, H = GAME_W + PANEL_W, GAME_H + BAR_H

# --- palette (moody stealth) ---------------------------------------------
C_BG = (10, 12, 16)
C_FLOOR_A = (26, 30, 38)
C_FLOOR_B = (23, 27, 34)
C_WALL = (15, 17, 22)
C_WALL_TOP = (44, 50, 62)
C_EXIT = (34, 170, 116)
C_PLAYER = (86, 166, 255)
C_GUARD = (232, 156, 58)
C_GUARD_ALERT = (226, 78, 66)
C_CONE_PATROL = (232, 200, 80)
C_CONE_CHASE = (226, 78, 66)
C_NOISE = (236, 238, 242)
C_PANEL = (16, 19, 25)
C_PANEL_LINE = (34, 40, 50)
C_INK = (222, 228, 236)
C_MUTE = (132, 142, 156)
C_ACCENT = (54, 211, 192)     # TypeSafe teal
C_LLM = (232, 168, 74)        # baseline amber
C_WIN = (70, 210, 140)
C_LOSE = (232, 96, 84)
C_BAR_BG = (30, 35, 44)

GUARD_SPEED = 1.7
PLAYER_SPEED = 2.7
FOV_DEG = 90
VIEW_RANGE = 6 * TILE
HEAR_RANGE = 5 * TILE
CATCH_RANGE = 0.55 * TILE
NOISE_TTL = 90
REQUEST_INTERVAL = 0.12       # min seconds between judgment requests per guard.
                              # Kept low on purpose: credits are plentiful, so guards
                              # re-decide freely as the situation changes and the panel
                              # stays live. (A guard still has at most one call in
                              # flight at a time, so this is bounded by latency.)

PATROL, INVESTIGATE, CHASE, RETURN = "patrol", "investigate_noise", "chase", "return_to_post"
COMPASS = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]


def tile_of(px, py):
    return int(px // TILE), int(py // TILE)


def center_of(tx, ty):
    return tx * TILE + TILE / 2, ty * TILE + TILE / 2


def is_wall(grid, tx, ty):
    if tx < 0 or ty < 0 or tx >= COLS or ty >= ROWS:
        return True
    return grid[ty][tx] == "#"


def compass(dx, dy):
    return COMPASS[int(round(math.atan2(dy, dx) / (math.pi / 4))) % 8]


def bfs_next(grid, start, goal):
    if start == goal:
        return None
    seen = {start}
    q = deque([(start, None)])
    while q:
        cur, step0 = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb = (cur[0] + dx, cur[1] + dy)
            if nb in seen or is_wall(grid, nb[0], nb[1]):
                continue
            seen.add(nb)
            s0 = step0 if step0 is not None else nb
            if nb == goal:
                return s0
            q.append((nb, s0))
    return None


def line_of_sight(grid, ax, ay, bx, by):
    tx0, ty0 = tile_of(ax, ay)
    tx1, ty1 = tile_of(bx, by)
    dx, dy = abs(tx1 - tx0), abs(ty1 - ty0)
    sx = 1 if tx0 < tx1 else -1
    sy = 1 if ty0 < ty1 else -1
    err = dx - dy
    x, y = tx0, ty0
    while True:
        if (x, y) != (tx0, ty0) and is_wall(grid, x, y):
            return False
        if (x, y) == (tx1, ty1):
            return True
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy


def ray_end(grid, x, y, ang, maxd, step=5):
    dx, dy = math.cos(ang), math.sin(ang)
    d = 0.0
    while d < maxd:
        d += step
        if is_wall(grid, *tile_of(x + dx * d, y + dy * d)):
            return x + dx * (d - step), y + dy * (d - step)
    return x + dx * maxd, y + dy * maxd


def cone_polygon(grid, g, steps=26):
    half = math.radians(FOV_DEG / 2)
    pts = [(g.x, g.y)]
    for i in range(steps + 1):
        a = g.facing - half + (2 * half) * i / steps
        pts.append(ray_end(grid, g.x, g.y, a, VIEW_RANGE))
    return pts


def can_see_player(grid, g, px, py):
    dx, dy = px - g.x, py - g.y
    dist = math.hypot(dx, dy)
    if dist < 1:
        return True
    if dist > VIEW_RANGE:
        return False
    ang = math.degrees(abs((math.atan2(dy, dx) - g.facing + math.pi) % (2 * math.pi) - math.pi))
    if ang > FOV_DEG / 2:
        return False
    return line_of_sight(grid, g.x, g.y, px, py)


@dataclass
class Guard:
    id: str
    x: float
    y: float
    waypoints: list
    wp_i: int = 0
    facing: float = 0.0
    mode: str = PATROL
    target: tuple | None = None
    noise_target: tuple | None = None
    last_seen: tuple | None = None
    alert: int = 0
    noticed: str | None = None
    pending: bool = False
    last_request: float = 0.0
    decision: object | None = None      # last runtime.judge.Result applied


@dataclass
class World:
    grid: list
    player: list
    exit_tile: tuple
    guards: list
    noises: list = field(default_factory=list)
    status: str = "play"


def load_world():
    grid = list(LEVEL)
    player, exit_tile = None, None
    for ty, row in enumerate(grid):
        for tx, ch in enumerate(row):
            if ch == "P":
                player = list(center_of(tx, ty))
            elif ch == "E":
                exit_tile = (tx, ty)
    grid = [row.replace("P", ".").replace("E", ".") for row in grid]
    guards = [
        Guard("G1", *center_of(14, 1), waypoints=[(14, 1), (14, 10), (11, 10), (11, 1)]),
        Guard("G2", *center_of(2, 10), waypoints=[(2, 10), (7, 10), (7, 6), (2, 6)]),
    ]
    return World(grid, player, exit_tile, guards)


# --- decisions run off the frame loop -------------------------------------
class DecisionService:
    """Runs judge.choice on a background asyncio loop. Guards request a decision and
    keep acting until it lands; results are polled from the frame loop."""

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        self._lock = threading.Lock()
        self._results = {}
        self._pending = set()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def request(self, gid, state, instructions, criteria, arm=None):
        with self._lock:
            if gid in self._pending:
                return
            self._pending.add(gid)
        fut = asyncio.run_coroutine_threadsafe(
            judge.choice(f"stealth.guard_action.{gid}", state, instructions, criteria, arm=arm),
            self._loop,
        )

        def _done(f):
            with self._lock:
                self._pending.discard(gid)
                try:
                    self._results[gid] = f.result()
                except Exception as e:  # keep last decision, note the failure
                    print(f"[decision] {gid} failed: {type(e).__name__}: {e}")
        fut.add_done_callback(_done)

    def take(self, gid):
        """Return (new_result_or_None, is_pending). Consumes a fresh result once."""
        with self._lock:
            res = self._results.pop(gid, None)
            return res, (gid in self._pending)

    def shutdown(self):
        try:
            fut = asyncio.run_coroutine_threadsafe(judge.aclose(), self._loop)
            fut.result(timeout=2)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)


def nearest_noise(world, g):
    best = None
    for n in world.noises:
        d = math.hypot(n["x"] - g.x, n["y"] - g.y)
        if d <= HEAR_RANGE and (best is None or d < best[0]):
            best = (d, n)
    return best[1] if best else None


def apply_decision(g, res, world):
    pick = res.pick or PATROL
    if pick == CHASE:
        g.mode, g.target = CHASE, g.last_seen or tile_of(*world.player)
        g.alert = max(g.alert, 2)
    elif pick in (INVESTIGATE, "call_backup"):
        g.mode = INVESTIGATE
        g.target = g.noise_target or g.target
        g.alert = max(g.alert, 1)
    else:  # patrol / return_to_post -> not baited, resume route
        g.mode = PATROL
        g.alert = max(0, g.alert - 1)


def update_ai(world, service):
    now = time.monotonic()
    for g in world.guards:
        px, py = world.player

        # instant rule: seeing the player is a chase, no judgment needed
        if can_see_player(world.grid, g, px, py):
            g.mode, g.target = CHASE, tile_of(px, py)
            g.last_seen, g.alert, g.noticed = g.target, 2, "sees the player"
            g.pending, g.decision = False, None
            continue

        # ambiguous case: a noise it can hear -> ask the judgment
        noise = nearest_noise(world, g)
        if noise is not None and not g.pending and (now - g.last_request) > REQUEST_INTERVAL:
            g.noise_target = tile_of(noise["x"], noise["y"])
            desc = f"heard a noise to the {compass(noise['x'] - g.x, noise['y'] - g.y)}"
            g.noticed = desc
            service.request(g.id, guard_state(g, [desc]), GUARD_INSTRUCTIONS, GUARD_ACTIONS)
            g.pending, g.last_request = True, now

        res, pending = service.take(g.id)
        g.pending = pending
        if res is not None:
            g.decision = res
            if res.dist and res.dist.get(res.pick, 1.0) >= CONFIDENCE_FLOOR:
                apply_decision(g, res, world)

        # reaching an investigate target with nothing there -> resume patrol
        gt = tile_of(g.x, g.y)
        if g.mode in (INVESTIGATE, RETURN) and g.target and gt == g.target:
            g.mode, g.alert, g.noticed = PATROL, 0, None
        if g.mode == PATROL:
            g.target = g.waypoints[g.wp_i]
            if gt == g.target:
                g.wp_i = (g.wp_i + 1) % len(g.waypoints)
                g.target = g.waypoints[g.wp_i]


def move_guard(world, g):
    if g.target is None:
        return
    nxt = bfs_next(world.grid, tile_of(g.x, g.y), g.target)
    goal = center_of(*nxt) if nxt else center_of(*g.target)
    dx, dy = goal[0] - g.x, goal[1] - g.y
    d = math.hypot(dx, dy)
    if d > 0.5:
        g.facing = math.atan2(dy, dx)
        g.x += GUARD_SPEED * dx / d
        g.y += GUARD_SPEED * dy / d


def move_player(world, dx, dy):
    if dx == 0 and dy == 0:
        return
    n = math.hypot(dx, dy)
    dx, dy = dx / n * PLAYER_SPEED, dy / n * PLAYER_SPEED
    r = TILE * 0.28
    px, py = world.player
    for ax, ay in ((dx, 0), (0, dy)):
        nx, ny = px + ax, py + ay
        corners = [(nx - r, ny - r), (nx + r, ny - r), (nx - r, ny + r), (nx + r, ny + r)]
        if not any(is_wall(world.grid, *tile_of(cx, cy)) for cx, cy in corners):
            px, py = nx, ny
    world.player = [px, py]


def step(world, service, keys, throw_at):
    if world.status != "play":
        return
    move_player(world, keys["right"] - keys["left"], keys["down"] - keys["up"])
    if throw_at is not None and throw_at[0] < GAME_W:
        world.noises.append({"x": throw_at[0], "y": throw_at[1], "ttl": NOISE_TTL})
    for n in world.noises:
        n["ttl"] -= 1
    world.noises = [n for n in world.noises if n["ttl"] > 0]

    update_ai(world, service)
    for g in world.guards:
        move_guard(world, g)
        if math.hypot(world.player[0] - g.x, world.player[1] - g.y) <= CATCH_RANGE \
                and can_see_player(world.grid, g, *world.player):
            world.status = "caught"
    if tile_of(*world.player) == world.exit_tile:
        world.status = "win"


# --- rendering ------------------------------------------------------------
def make_vignette():
    surf = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
    cx, cy = GAME_W / 2, GAME_H / 2
    maxd = math.hypot(cx, cy)
    for r in range(int(maxd), 0, -8):
        a = int(90 * (r / maxd) ** 2)
        pygame.draw.circle(surf, (0, 0, 0, a), (int(cx), int(cy)), r)
    return surf


def draw_game(screen, fonts, world, vignette, tick):
    for ty in range(ROWS):
        for tx in range(COLS):
            r = pygame.Rect(tx * TILE, ty * TILE, TILE, TILE)
            if is_wall(world.grid, tx, ty):
                pygame.draw.rect(screen, C_WALL, r)
                pygame.draw.rect(screen, C_WALL_TOP, (r.x, r.y, TILE, 4))
            else:
                pygame.draw.rect(screen, C_FLOOR_A if (tx + ty) % 2 else C_FLOOR_B, r)

    ex, ey = world.exit_tile
    pulse = 6 + 2 * math.sin(tick * 0.08)
    pygame.draw.rect(screen, C_EXIT, (ex * TILE + 6, ey * TILE + 6, TILE - 12, TILE - 12), border_radius=7)
    glow = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
    pygame.draw.rect(glow, (*C_EXIT, 60), (int(pulse), int(pulse), TILE - int(2 * pulse), TILE - int(2 * pulse)), border_radius=8)
    screen.blit(glow, (ex * TILE, ey * TILE))

    # vision cones (raycast, translucent)
    cone = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
    for g in world.guards:
        color = C_CONE_CHASE if g.mode == CHASE else C_CONE_PATROL
        pygame.draw.polygon(cone, (*color, 40), cone_polygon(world.grid, g))
    screen.blit(cone, (0, 0))

    # noise ripples
    for n in world.noises:
        rad = int((NOISE_TTL - n["ttl"]) * 0.5) + 4
        a = max(0, int(210 * n["ttl"] / NOISE_TTL))
        ring = pygame.Surface((rad * 2 + 4, rad * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(ring, (*C_NOISE, a), (rad + 2, rad + 2), rad, 2)
        screen.blit(ring, (n["x"] - rad - 2, n["y"] - rad - 2))

    # player: bright, outlined, labeled so it never gets lost in the scene
    pxi, pyi = int(world.player[0]), int(world.player[1])
    pgl = pygame.Surface((TILE * 2, TILE * 2), pygame.SRCALPHA)
    pygame.draw.circle(pgl, (*C_PLAYER, 70), (TILE, TILE), int(TILE * 0.85))
    screen.blit(pgl, (pxi - TILE, pyi - TILE))
    pygame.draw.circle(screen, (255, 255, 255), (pxi, pyi), int(TILE * 0.38))
    pygame.draw.circle(screen, C_PLAYER, (pxi, pyi), int(TILE * 0.31))
    you = fonts["s"].render("YOU", True, (255, 255, 255))
    screen.blit(you, (pxi - you.get_width() // 2, pyi - int(TILE * 0.82)))

    # guards with facing wedge
    for g in world.guards:
        col = C_GUARD_ALERT if g.mode == CHASE else C_GUARD
        pygame.draw.circle(screen, col, (int(g.x), int(g.y)), int(TILE * 0.3))
        tip = (g.x + math.cos(g.facing) * TILE * 0.42, g.y + math.sin(g.facing) * TILE * 0.42)
        left = (g.x + math.cos(g.facing + 2.4) * TILE * 0.24, g.y + math.sin(g.facing + 2.4) * TILE * 0.24)
        right = (g.x + math.cos(g.facing - 2.4) * TILE * 0.24, g.y + math.sin(g.facing - 2.4) * TILE * 0.24)
        pygame.draw.polygon(screen, C_INK, (tip, left, right))
        if g.pending:
            dots = "." * (1 + (tick // 12) % 3)
            screen.blit(fonts["s"].render("deciding" + dots, True, C_INK), (g.x - 26, g.y - TILE * 0.62))

    screen.blit(vignette, (0, 0))


def bar_row(screen, fonts, x, y, w, label, prob, hot):
    screen.blit(fonts["s"].render(label, True, C_INK if hot else C_MUTE), (x, y - 1))
    bx, bw = x + 118, w - 118 - 34
    pygame.draw.rect(screen, C_BAR_BG, (bx, y + 1, bw, 9), border_radius=3)
    if prob > 0:
        pygame.draw.rect(screen, C_ACCENT if hot else (70, 84, 100),
                         (bx, y + 1, max(2, int(bw * prob)), 9), border_radius=3)
    screen.blit(fonts["s"].render(f"{prob:.2f}", True, C_MUTE), (bx + bw + 6, y - 1))


def draw_card(screen, fonts, x, y, w, g):
    dot = C_GUARD_ALERT if g.mode == CHASE else C_GUARD
    pygame.draw.circle(screen, dot, (x + 8, y + 8), 6)
    screen.blit(fonts["m"].render(g.id, True, C_INK), (x + 22, y))
    res = g.decision
    arm = (res.arm if res else "typesafe")
    label = {"typesafe": "Instinct", "baseline": "LLM"}.get(arm, arm)
    ac = C_ACCENT if arm == "typesafe" else C_LLM
    pill = fonts["s"].render(label, True, C_BG)
    pw = pill.get_width() + 14
    pygame.draw.rect(screen, ac, (x + w - pw, y, pw, 16), border_radius=8)
    screen.blit(pill, (x + w - pw + 7, y + 1))

    y += 24
    trigger = g.noticed or ("chasing" if g.mode == CHASE else "on patrol")
    screen.blit(fonts["s"].render(trigger, True, C_MUTE), (x, y))
    y += 18

    if g.mode == CHASE:
        screen.blit(fonts["m"].render("chase  (rule: in sight)", True, C_GUARD_ALERT), (x, y))
        return
    if res is None:
        txt = "deciding..." if g.pending else "patrolling"
        screen.blit(fonts["m"].render(txt, True, C_MUTE), (x, y))
        return

    screen.blit(fonts["m"].render(res.pick, True, C_ACCENT), (x, y))
    y += 22
    dist = res.dist or {}
    for act in GUARD_ACTIONS:
        bar_row(screen, fonts, x, y, w, act, float(dist.get(act, 0.0)), act == res.pick)
        y += 16
    y += 4
    conf = f"conf {res.confidence:.2f}" if res.confidence is not None else "conf -"
    lat = f"{res.latency_ms:.0f} ms" if res.latency_ms is not None else "- ms"
    screen.blit(fonts["s"].render(f"{conf}    {lat}", True, C_MUTE), (x, y))


def draw_panel(screen, fonts, world, tick):
    px = GAME_W
    pygame.draw.rect(screen, C_PANEL, (px, 0, PANEL_W, H))
    pygame.draw.line(screen, C_PANEL_LINE, (px, 0), (px, H))
    x = px + 18
    screen.blit(fonts["l"].render("NPC decisions", True, C_INK), (x, 16))
    screen.blit(fonts["s"].render("live typed judgments driving each guard", True, C_MUTE), (x, 40))
    pygame.draw.line(screen, C_PANEL_LINE, (px + 14, 62), (W - 14, 62))
    y = 78
    for g in world.guards:
        draw_card(screen, fonts, x, y, PANEL_W - 34, g)
        y += 176
        pygame.draw.line(screen, C_PANEL_LINE, (px + 14, y - 12), (W - 14, y - 12))


def draw_bar(screen, fonts, world):
    y = GAME_H
    pygame.draw.rect(screen, C_BG, (0, y, GAME_W, BAR_H))
    if world.status == "play":
        msg, col = "WASD move   ·   click to throw a distraction   ·   reach the green exit", C_MUTE
    elif world.status == "win":
        msg, col = "ESCAPED. You reached the exit.   R to restart", C_WIN
    else:
        msg, col = "CAUGHT. A guard spotted you.   R to restart", C_LOSE
    screen.blit(fonts["m"].render(msg, True, col), (14, y + 9))


def build_fonts():
    return {
        "s": pygame.font.SysFont("menlo,monospace", 12),
        "m": pygame.font.SysFont("menlo,monospace", 15),
        "l": pygame.font.SysFont("helvetica,arial", 18, bold=True),
    }


# --- loops ----------------------------------------------------------------
def main():
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Instinct Stealth (step 4: judgments drive the guards)")
    fonts = build_fonts()
    clock = pygame.time.Clock()
    vignette = make_vignette()
    proj = trace.init()
    if proj:
        print(f"[weave] tracing guard decisions to project '{proj}'")
    world = load_world()
    service = DecisionService()
    tick = 0

    running = True
    while running:
        throw_at = None
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                elif e.key == pygame.K_r:
                    world = load_world()
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and world.status == "play":
                throw_at = pygame.mouse.get_pos()

        p = pygame.key.get_pressed()
        keys = {
            "left": p[pygame.K_a] or p[pygame.K_LEFT],
            "right": p[pygame.K_d] or p[pygame.K_RIGHT],
            "up": p[pygame.K_w] or p[pygame.K_UP],
            "down": p[pygame.K_s] or p[pygame.K_DOWN],
        }
        step(world, service, keys, throw_at)
        screen.fill(C_BG)
        draw_game(screen, fonts, world, vignette, tick)
        draw_panel(screen, fonts, world, tick)
        draw_bar(screen, fonts, world)
        pygame.display.flip()
        tick += 1
        clock.tick(60)

    service.shutdown()
    pygame.quit()


def selftest(frames=150):
    """Headless: exercise the loop, the decision plumbing, and rendering without a
    window or network. judge.choice is stubbed so no API calls happen."""
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    async def _stub(key, state, instructions, criteria, arm=None):
        await asyncio.sleep(0)
        return judge.Result(pick=INVESTIGATE, dist={a: (0.7 if a == INVESTIGATE else 0.075) for a in GUARD_ACTIONS},
                            confidence=0.8, latency_ms=5.0, arm="mock")
    judge.choice = _stub  # type: ignore

    pygame.init()
    screen = pygame.display.set_mode((W, H))
    fonts = build_fonts()
    vignette = make_vignette()
    world = load_world()
    service = DecisionService()
    ever_applied = False
    for i in range(frames):
        keys = {"left": 0, "right": 0, "up": 0, "down": 0}   # keep player still so no chase
        # throw a noise right on a guard so it is guaranteed audible
        throw_at = (int(world.guards[1].x), int(world.guards[1].y)) if i in (10, 60) else None
        step(world, service, keys, throw_at)
        time.sleep(0.006)  # let the background decision loop run
        ever_applied = ever_applied or any(g.decision is not None for g in world.guards)
        screen.fill(C_BG)
        draw_game(screen, fonts, world, vignette, i)
        draw_panel(screen, fonts, world, i)
        draw_bar(screen, fonts, world)
    modes = {g.id: g.mode for g in world.guards}
    service.shutdown()
    pygame.quit()
    print(f"selftest OK: ran {frames} frames, status={world.status}, "
          f"decision applied at least once={ever_applied}, final modes={modes}")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    main()
