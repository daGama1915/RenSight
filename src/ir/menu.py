"""
ir/menu.py
----------
Core data model for a single narrative choice point extracted from a Ren'Py
script.  This is the canonical representation shared by the parser, graph
builder, and survey generator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class MenuEntry:
    """
    Represents one player-choice menu extracted from a Ren'Py label.

    Attributes:
        choice_id:    Stable identifier, e.g. ``scene03_menu1``.
        file:         Relative path to the source .rpy file.
        label:        Ren'Py label that contains this menu.
        line:         1-based line number of the ``menu:`` keyword.
        context:      Dialogue lines that immediately precede the menu.
        choices:      Player-visible choice strings (no surrounding quotes).
        metadata:     Optional freeform dict for downstream annotation.
    """

    choice_id: str
    file:      str
    label:     str
    line:      int
    context:   List[str]       = field(default_factory=list)
    choices:   List[str]       = field(default_factory=list)
    metadata:  Dict[str, str]  = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MenuEntry":
        """Construct a MenuEntry from a plain dictionary (e.g. loaded from JSON)."""
        return cls(
            choice_id = data["choice_id"],
            file      = data["file"],
            label     = data["label"],
            line      = int(data.get("line", 0)),
            context   = list(data.get("context", [])),
            choices   = list(data.get("choices", [])),
            metadata  = dict(data.get("metadata", {})),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def is_valid(self) -> bool:
        """Return True if this entry has at least one choice."""
        return bool(self.choices)

    def __repr__(self) -> str:
        return (f"MenuEntry({self.choice_id!r}, label={self.label!r}, "
                f"choices={len(self.choices)})")
