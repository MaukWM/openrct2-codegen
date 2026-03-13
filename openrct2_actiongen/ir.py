"""IR schema for actions.json — the output of the parser."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ActionParameter(BaseModel):
    """A single parameter accepted by a game action."""

    name: str
    type: Literal["boolean", "number", "string"]
    cpp_type: str


class Action(BaseModel):
    """A single game action with its full parameter signature."""

    js_name: str         # "ridecreate"
    cpp_class: str       # "RideCreateAction"
    game_command: str    # "CreateRide"
    # Derived from subdirectory name (e.g. "ride", "park", "terraform").
    # Defaults to "general" for pre-v0.4.32 where actions are flat in actions/.
    category: str
    parameters: list[ActionParameter]


class ActionsIR(BaseModel):
    """Top-level IR: the full actions.json schema."""

    openrct2_version: str
    api_version: int
    generated_at: str
    generator_version: str
    actions: list[Action]
