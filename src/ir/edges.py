"""
ir/edges.py
-----------
Edge type definitions for the NarrativeGraph.

Edges always connect label→label (the primary narrative flow).
Additional edge types model the different ways a Ren'Py script can
transfer control between labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EdgeType(Enum):
    JUMP        = "jump"        # unconditional jump statement
    CALL        = "call"        # call statement (implies eventual return)
    SEQUENTIAL  = "sequential"  # one label falls through to the next in file
    CHOICE      = "choice"      # player choice → target label


@dataclass
class EdgeAttrs:
    """
    Attribute schema for a NarrativeGraph edge.

    NetworkX stores these as a dict on each edge.
    """
    edge_type:  str   = EdgeType.SEQUENTIAL.value
    file:       str   = ""
    line:       int   = 0
    choice_text: str  = ""   # non-empty only for CHOICE edges

    def to_dict(self) -> dict:
        return {
            "edge_type":   self.edge_type,
            "file":        self.file,
            "line":        self.line,
            "choice_text": self.choice_text,
        }
