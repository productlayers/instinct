"""Pygame stealth level: sneak past guards to reach the exit.

Step 3 (this file): playable with RULES-BASED guards, patrol, see the player and
chase, hear a thrown noise and investigate. The guard decision is isolated in
`guard_think()` so step 4 can swap it for a TypeSafe judgment without touching the
rest of the game.

Controls: WASD / arrows to move. Click to throw a distraction (makes a noise there).
R to restart. Esc to quit.  Run: `python -m games.stealth.game`
Headless self-test (no window): `python -m games.stealth.game --selftest`
"""
from __future__ import annotations

import math
import sys
from collections import deque
from dataclasses import dataclass, field

import pygame

# --- layout ---------------------------------------------------------------
TILE = 36
LEVEL = [
    "####################",
    "#........#.........#",
    "#.P......#.......E.#",
    "#........#.........#",
    "#....#########.....#",
    "#..................#",
    "#..................#",
    "#.....########.....#",
    "#........#.........#",
    "#........#.........#",
    "#........#.........#",
    "####################",
]
COLS, ROWS = len(LEVEL[0]), len(LEVEL)
W, H = COLS * TILE, ROWS * TILE + 40  # +40 for the HUD strip

# --- colors ---------------------------------------------------------------
C_FLOOR = (28, 32, 39)
C_WALL = (12, 14, 18)
C_GRID = (22, 26, 32)
C_EXIT = (30, 158, 106)
C_PLAYER = (70, 150, 240)
C_GUARD = (230, 150, 50)
C_GUARD_ALERT = (220, 70, 60)
C_SEE_PATROL = (230, 200, 70)
C_SEE_CHASE = (220, 70, 60)
C_NOISE = (235, 235, 235)
C_TEXT = (210, 216, 224)
C_WIN = (60, 200, 130)
C_LOSE = (220, 80, 70)

# --- guard tuning ---------------------------------------------------------
GUARD_SPEED = 1.7          # px per frame
PLAYER_SPEED = 2.6
FOV_DEG = 90
VIEW_RANGE = 6 * TILE
HEAR_RANGE = 5 * TILE
CATCH_RANGE = 0.6 * TILE
NOISE_TTL = 90             # frames a noise stays audible/visible

PATROL, INVESTIGATE, CHASE, RETURN = "patrol", "investigate", "chase", "return"


def tile_of(px: float, py: float) -> tuple[int, int]:
    return int(px // TILE), int(py // TILE)


def center_of(tx: int, ty: int) -> tuple[float, float]:
    return tx * TILE + TILE / 2, ty * TILE + TILE / 2


def is_wall(grid, tx: int, ty: int) -> bool:
    if tx < 0 or ty < 0 or tx >= COLS or ty >= ROWS:
        return True
    return grid[ty][tx] == "#"


def bfs_next(grid, start: tuple[int, int], goal: tuple[int, int]):
    """Return the next tile to step toward on a shortest path, or None."""
    if start == goal:
        return None
    seen = {start}
    q = deque([(start, None)])
    first_step = {}
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


def line_of_sight(grid, ax, ay, bx, by) -> bool:
    """True if no wall tile lies between world points a and b (grid Bresenham)."""
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


@dataclass
class Guard:
    x: float
    y: float
    waypoints: list[tuple[int, int]]
    wp_i: int = 0
    facing: float = 0.0
    mode: str = PATROL
    target: tuple[int, int] | None = None      # tile
    last_seen: tuple[int, int] | None = None
    alert: int = 0                              # 0 calm, 1 wary, 2 alert
    noticed: str | None = None                 # last thing it reacted to (for HUD/step 4)


@dataclass
class World:
    grid: list[str]
    player: list[float]
    exit_tile: tuple[int, int]
    guards: list[Guard]
    noises: list[dict] = field(default_factory=list)
    status: str = "play"   # play | win | caught


def load_world() -> World:
    grid = [row for row in LEVEL]
    player = None
    exit_tile = None
    for ty, row in enumerate(grid):
        for tx, ch in enumerate(row):
            if ch == "P":
                player = list(center_of(tx, ty))
            elif ch == "E":
                exit_tile = (tx, ty)
    # blank the markers so they render as floor
    grid = [row.replace("P", ".").replace("E", ".") for row in grid]
    guards = [
        Guard(*center_of(14, 2), waypoints=[(14, 2), (14, 10), (11, 10), (11, 2)]),
        Guard(*center_of(3, 8), waypoints=[(3, 8), (7, 8), (7, 5), (3, 5)]),
    ]
    return World(grid, player, exit_tile, guards)


def can_see_player(grid, g: Guard, px: float, py: float) -> bool:
    dx, dy = px - g.x, py - g.y
    dist = math.hypot(dx, dy)
    if dist > VIEW_RANGE or dist < 1:
        return dist < 1
    ang = math.degrees(abs((math.atan2(dy, dx) - g.facing + math.pi) % (2 * math.pi) - math.pi))
    if ang > FOV_DEG / 2:
        return False
    return line_of_sight(grid, g.x, g.y, px, py)


def guard_think(world: World, g: Guard) -> None:
    """RULES-BASED decision (step 3). Sets g.mode and g.target.

    Step 4 replaces this with a TypeSafe judgment: build state from the world, call
    judge.choice, and map the pick onto the same (mode, target). Everything else in
    this file stays the same.
    """
    px, py = world.player
    ptile = tile_of(px, py)

    if can_see_player(world.grid, g, px, py):
        g.mode, g.target, g.last_seen, g.alert = CHASE, ptile, ptile, 2
        g.noticed = "sees the player"
        return

    # heard a noise recently?
    for n in world.noises:
        if math.hypot(n["x"] - g.x, n["y"] - g.y) <= HEAR_RANGE:
            g.mode, g.target, g.alert = INVESTIGATE, tile_of(n["x"], n["y"]), max(g.alert, 1)
            g.noticed = "heard a noise"
            return

    gtile = tile_of(g.x, g.y)
    if g.mode == CHASE:                      # lost sight -> check last seen
        g.mode, g.target = INVESTIGATE, g.last_seen
    if g.mode in (INVESTIGATE, RETURN) and g.target and gtile == g.target:
        g.mode, g.alert, g.noticed = PATROL, 0, None   # gave up, resume patrol
    if g.mode == PATROL:
        g.target = g.waypoints[g.wp_i]
        if gtile == g.target:
            g.wp_i = (g.wp_i + 1) % len(g.waypoints)
            g.target = g.waypoints[g.wp_i]


def move_guard(world: World, g: Guard) -> None:
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


def move_player(world: World, dx: float, dy: float) -> None:
    if dx == 0 and dy == 0:
        return
    n = math.hypot(dx, dy)
    dx, dy = dx / n * PLAYER_SPEED, dy / n * PLAYER_SPEED
    r = TILE * 0.3
    px, py = world.player
    # move axis-by-axis so we slide along walls
    for ax, ay in ((dx, 0), (0, dy)):
        nx, ny = px + ax, py + ay
        corners = [(nx - r, ny - r), (nx + r, ny - r), (nx - r, ny + r), (nx + r, ny + r)]
        if not any(is_wall(world.grid, *tile_of(cx, cy)) for cx, cy in corners):
            px, py = nx, ny
    world.player = [px, py]


def step(world: World, keys, throw_at) -> None:
    if world.status != "play":
        return
    dx = (keys["right"] - keys["left"])
    dy = (keys["down"] - keys["up"])
    move_player(world, dx, dy)

    if throw_at is not None:
        world.noises.append({"x": throw_at[0], "y": throw_at[1], "ttl": NOISE_TTL})
    for n in world.noises:
        n["ttl"] -= 1
    world.noises = [n for n in world.noises if n["ttl"] > 0]

    for g in world.guards:
        guard_think(world, g)
        move_guard(world, g)
        if math.hypot(world.player[0] - g.x, world.player[1] - g.y) <= CATCH_RANGE \
                and can_see_player(world.grid, g, *world.player):
            world.status = "caught"

    if tile_of(*world.player) == world.exit_tile:
        world.status = "win"


# --- rendering ------------------------------------------------------------
def visible_overlay(surf, world: World) -> None:
    tint = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
    for g in world.guards:
        color = C_SEE_CHASE if g.mode == CHASE else C_SEE_PATROL
        gt = tile_of(g.x, g.y)
        rng = int(VIEW_RANGE // TILE) + 1
        for ty in range(max(0, gt[1] - rng), min(ROWS, gt[1] + rng + 1)):
            for tx in range(max(0, gt[0] - rng), min(COLS, gt[0] + rng + 1)):
                if is_wall(world.grid, tx, ty):
                    continue
                cx, cy = center_of(tx, ty)
                if can_see_player(world.grid, g, cx, cy) or _tile_in_cone(world.grid, g, cx, cy):
                    tint.fill((*color, 46))
                    surf.blit(tint, (tx * TILE, ty * TILE))


def _tile_in_cone(grid, g: Guard, cx, cy) -> bool:
    dx, dy = cx - g.x, cy - g.y
    dist = math.hypot(dx, dy)
    if dist > VIEW_RANGE:
        return False
    ang = math.degrees(abs((math.atan2(dy, dx) - g.facing + math.pi) % (2 * math.pi) - math.pi))
    return ang <= FOV_DEG / 2 and line_of_sight(grid, g.x, g.y, cx, cy)


def draw(screen, font, world: World) -> None:
    screen.fill(C_WALL)
    for ty in range(ROWS):
        for tx in range(COLS):
            r = pygame.Rect(tx * TILE, ty * TILE, TILE, TILE)
            if is_wall(world.grid, tx, ty):
                pygame.draw.rect(screen, C_WALL, r)
            else:
                pygame.draw.rect(screen, C_FLOOR, r)
                pygame.draw.rect(screen, C_GRID, r, 1)
    ex, ey = world.exit_tile
    pygame.draw.rect(screen, C_EXIT, (ex * TILE + 5, ey * TILE + 5, TILE - 10, TILE - 10), border_radius=6)

    visible_overlay(screen, world)

    for n in world.noises:
        rad = int((NOISE_TTL - n["ttl"]) * 0.4) + 4
        a = max(0, int(200 * n["ttl"] / NOISE_TTL))
        ring = pygame.Surface((rad * 2 + 2, rad * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(ring, (*C_NOISE, a), (rad + 1, rad + 1), rad, 2)
        screen.blit(ring, (n["x"] - rad, n["y"] - rad))

    for g in world.guards:
        col = C_GUARD_ALERT if g.mode == CHASE else C_GUARD
        pygame.draw.circle(screen, col, (int(g.x), int(g.y)), int(TILE * 0.32))
        fx = g.x + math.cos(g.facing) * TILE * 0.5
        fy = g.y + math.sin(g.facing) * TILE * 0.5
        pygame.draw.line(screen, col, (g.x, g.y), (fx, fy), 3)

    pygame.draw.circle(screen, C_PLAYER, (int(world.player[0]), int(world.player[1])), int(TILE * 0.3))

    pygame.draw.rect(screen, C_WALL, (0, ROWS * TILE, W, 40))
    if world.status == "play":
        msg = "WASD/arrows move   •   click to throw a distraction   •   reach the green exit"
        col = C_TEXT
    elif world.status == "win":
        msg = "ESCAPED, you reached the exit.   R to restart"
        col = C_WIN
    else:
        msg = "CAUGHT, a guard spotted you.   R to restart"
        col = C_LOSE
    screen.blit(font.render(msg, True, col), (12, ROWS * TILE + 12))


# --- loops ----------------------------------------------------------------
def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Instinct Stealth (step 3: rules-based guards)")
    font = pygame.font.SysFont("menlo,monospace", 15)
    clock = pygame.time.Clock()
    world = load_world()

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

        pressed = pygame.key.get_pressed()
        keys = {
            "left": pressed[pygame.K_a] or pressed[pygame.K_LEFT],
            "right": pressed[pygame.K_d] or pressed[pygame.K_RIGHT],
            "up": pressed[pygame.K_w] or pressed[pygame.K_UP],
            "down": pressed[pygame.K_s] or pressed[pygame.K_DOWN],
        }
        step(world, keys, throw_at)
        draw(screen, font, world)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


def selftest(frames: int = 200) -> int:
    """Headless: run the simulation without a window and assert it doesn't crash."""
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    font = pygame.font.SysFont("monospace", 15)
    world = load_world()
    for i in range(frames):
        # walk the player right-and-down; throw once early to exercise noise + hearing
        keys = {"left": 0, "right": 1, "up": 0, "down": 1 if i % 3 else 0}
        throw_at = (10 * TILE, 6 * TILE) if i == 20 else None
        step(world, keys, throw_at)
        draw(screen, font, world)
    pygame.quit()
    print(f"selftest OK: ran {frames} frames, final status = {world.status}")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    main()
