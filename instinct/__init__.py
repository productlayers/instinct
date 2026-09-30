"""Instinct: NPC decisions that learn the player, fast enough for a game loop."""
from .brain import Brain, Decision
from .jev import Verdict

__all__ = ["Brain", "Decision", "Verdict"]
__version__ = "0.1.0"
