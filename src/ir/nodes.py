"""
ir/nodes.py
-----------
Node type definitions for the NarrativeGraph.

The graph uses string IDs for NetworkX nodes, with rich attribute dicts.
These dataclasses serve as the canonical attribute schemas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional


class NodeType(Enum):
    LABEL  = "label"
    MENU   = "menu"
    CHOICE = "choice"
    START  = "start"     # synthetic entry point


@dataclass
class LabelNodeAttrs:
    """
    Attributes stored on a label node in the NarrativeGraph.

    The node ID in NetworkX is the label name string.
    """
    node_type:   str = NodeType.LABEL.value
    file:        str = ""
    line:        int = 0
    menu_ids:    List[str] = field(default_factory=list)  # choice_ids of menus
    is_entry:    bool = False   # True for the 'start' label

    def to_dict(self) -> dict:
        return {
            "node_type": self.node_type,
            "file":      self.file,
            "line":      self.line,
            "menu_ids":  self.menu_ids,
            "is_entry":  self.is_entry,
        }


@dataclass
class MenuNodeAttrs:
    """
    Attributes stored on a menu node in the NarrativeGraph.

    The node ID is the choice_id string (e.g. ``scene03_menu1``).
    """
    node_type:  str = NodeType.MENU.value
    label:      str = ""
    file:       str = ""
    line:       int = 0
    choices:    List[str] = field(default_factory=list)
    context:    List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "node_type": self.node_type,
            "label":     self.label,
            "file":      self.file,
            "line":      self.line,
            "choices":   self.choices,
            "context":   self.context,
        }
