"""
ir — Intermediate Representation
---------------------------------
All shared data structures passed between pipeline stages.
"""

from .menu           import MenuEntry
from .parsed_script  import ParsedScript, LabelInfo, NarrativeEdge
from .nodes          import NodeType, LabelNodeAttrs, MenuNodeAttrs
from .edges          import EdgeType, EdgeAttrs
from .narrative_graph import NarrativeGraph

__all__ = [
    "MenuEntry",
    "ParsedScript",
    "LabelInfo",
    "NarrativeEdge",
    "NodeType",
    "LabelNodeAttrs",
    "MenuNodeAttrs",
    "EdgeType",
    "EdgeAttrs",
    "NarrativeGraph",
]
