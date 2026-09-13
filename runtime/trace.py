"""Weave tracing. Call init() once at startup. After that every judge.choice is a
traced Weave op (its inputs and the Result), and the W&B Inference baseline is
auto-traced too because Weave patches the openai client. See BUILD.md section 7.
"""
import os

import weave

from runtime import config  # importing loads the repo .env (WANDB_API_KEY, entity)

_inited = False
_project = None


def _default_project() -> str:
    """Build an explicit 'entity/project' so Weave never has to guess the entity."""
    if os.environ.get("WEAVE_PROJECT"):
        return os.environ["WEAVE_PROJECT"]
    entity = os.environ.get("WANDB_ENTITY", "")
    inf = os.environ.get("WANDB_INFERENCE_PROJECT", "")   # "entity/project"
    if not entity and "/" in inf:
        entity = inf.split("/", 1)[0]
    return f"{entity}/instinct-stealth" if entity else "instinct-stealth"


def init(project: str | None = None) -> str | None:
    """Initialize Weave once. Returns the project name if it connected, else None."""
    global _inited, _project
    if _inited:
        return _project
    project = project or _default_project()
    try:
        weave.init(project)
        _inited, _project = True, project
        return project
    except Exception as e:
        print(f"[trace] weave.init failed: {type(e).__name__}: {e}")
        return None


def is_on() -> bool:
    return _inited
