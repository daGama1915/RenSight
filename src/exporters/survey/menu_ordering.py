"""
exporters/survey/menu_ordering.py
-----------------------------------
Menu ordering and deduplication utilities for the survey builder.

v0.2 changes vs v0.1
----------------------
* ``narrative_flow`` order now accepts a ``NarrativeGraph`` directly in
  addition to ``game_dir``.  When a graph is supplied it is used for BFS
  traversal; otherwise the graph is built on demand from the game directory.
* All other ordering modes and the deduplication logic are unchanged.

Order modes
-----------
as_extracted    — original parser scan order (default)
file_line       — sort by (file, line number)
label_alpha     — sort by label name alphabetically, then menu index
choice_id       — natural sort on the choice_id string
narrative_flow  — BFS traversal order on the narrative graph
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ constants

ALL_ORDER_MODES    = ("as_extracted", "file_line", "label_alpha",
                      "choice_id", "narrative_flow")
ORDER_AS_EXTRACTED = "as_extracted"
ORDER_FILE_LINE    = "file_line"
ORDER_LABEL_ALPHA  = "label_alpha"
ORDER_CHOICE_ID    = "choice_id"
ORDER_NARRATIVE    = "narrative_flow"


# ------------------------------------------------------------------ typing shim
# Import MenuEntry for type hints without creating a hard circular dependency.

try:
    from ir.menu            import MenuEntry
    from ir.narrative_graph import NarrativeGraph
except ImportError:
    MenuEntry      = object   # type: ignore[assignment,misc]
    NarrativeGraph = object   # type: ignore[assignment,misc]


# ------------------------------------------------------------------ natural sort

def _natural_key(s: str) -> List:
    """Key function for natural (human) sort order."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]


# ------------------------------------------------------------------ dedup

def deduplicate_nodes(
    nodes: List[MenuEntry],
) -> Tuple[List[MenuEntry], int]:
    """
    Remove duplicate menus where BOTH ``choice_id`` AND ``choices`` list
    are identical.  Keeps the first occurrence.

    Returns:
        (deduplicated_list, number_removed)
    """
    seen:    Dict[tuple, bool] = {}
    result:  List[MenuEntry]   = []
    removed = 0

    for node in nodes:
        fingerprint = (node.choice_id, tuple(node.choices))
        if fingerprint in seen:
            removed += 1
        else:
            seen[fingerprint] = True
            result.append(node)

    if removed:
        logger.info("Deduplication removed %d duplicate menu(s).", removed)
    return result, removed


# ------------------------------------------------------------------ natural file stable sort

def _natural_file_stable_sort(nodes: list) -> list:
    """
    Reorder *nodes* so file groups appear in natural (numeric) order —
    e.g. day1 → day2 → day10 → day11 → day100 — while preserving the
    relative order of nodes *within* each file.

    This is applied to ``as_extracted`` order so that the file scanner's
    alphabetical walk order does not bleed into the survey output.
    It is also the basis for consistent ordering across TXT, Markdown,
    and HTML, regardless of which sort mode was chosen.
    """
    groups: dict = {}
    for node in nodes:
        groups.setdefault(node.file, []).append(node)
    sorted_files = sorted(groups.keys(), key=_natural_key)
    result = []
    for f in sorted_files:
        result.extend(groups[f])
    return result


# ------------------------------------------------------------------ sort

def sort_nodes(
    nodes:    List[MenuEntry],
    mode:     str = ORDER_AS_EXTRACTED,
    graph:    Optional[NarrativeGraph] = None,
    game_dir: Optional[str] = None,
) -> List[MenuEntry]:
    """
    Return *nodes* reordered according to *mode*.

    Args:
        nodes:    Flat list of MenuEntry objects.
        mode:     One of ``ALL_ORDER_MODES``.
        graph:    Pre-built NarrativeGraph (used for ``narrative_flow``).
        game_dir: Game directory (used to build a graph on demand if *graph*
                  is not supplied and mode is ``narrative_flow``).

    Returns:
        New list (does not modify the input list).
    """
    if mode == ORDER_AS_EXTRACTED:
        return _natural_file_stable_sort(nodes)

    if mode == ORDER_FILE_LINE:
        return sorted(nodes, key=lambda m: (_natural_key(m.file), m.line))

    if mode == ORDER_LABEL_ALPHA:
        return sorted(nodes, key=lambda m: (m.label.lower(), _natural_key(m.choice_id)))

    if mode == ORDER_CHOICE_ID:
        return sorted(nodes, key=lambda m: _natural_key(m.choice_id))

    if mode == ORDER_NARRATIVE:
        return _sort_narrative_flow(nodes, graph=graph, game_dir=game_dir)

    logger.warning("Unknown order mode '%s'; falling back to as_extracted.", mode)
    return list(nodes)


# ------------------------------------------------------------------ narrative flow

def _sort_narrative_flow(
    nodes:    List[MenuEntry],
    graph:    Optional[NarrativeGraph] = None,
    game_dir: Optional[str] = None,
) -> List[MenuEntry]:
    """
    Orders menus based on a Breadth-First Search (BFS) of the narrative graph.
    Unreachable menus are placed at the end, grouped cleanly by file and line.
    """
    ng = graph

    if ng is None and game_dir is not None:
        ng = _build_graph_from_dir(game_dir)

    if ng is None:
        logger.warning(
            "narrative_flow requires a NarrativeGraph or game_dir; "
            "falling back to file_line order."
        )
        return sorted(nodes, key=lambda m: (_natural_key(m.file), m.line))

    # Build BFS order of label names
    bfs = ng.bfs_order(start="start")
    label_rank: Dict[str, int] = {label: i for i, label in enumerate(bfs)}

    # Build (label, menu_index) rank from choice_id
    def _menu_rank(node):
        # If the label wasn't found in BFS, it gets a massive penalty (len(bfs))
        label_pos = label_rank.get(node.label, len(bfs))

        # Extract the menu number from choice_id, e.g. "scene03_menu2" → 2
        m = re.search(r'_menu(\d+)$', node.choice_id)
        menu_idx = int(m.group(1)) if m else 0

        # Use _natural_key on the file path so "day100.rpy" sorts AFTER "day11.rpy"
        # rather than between "day10.rpy" and "day11.rpy" (alphanumeric pitfall).
        return (label_pos, _natural_key(node.file), node.line, menu_idx)

    return sorted(nodes, key=_menu_rank)


def _build_graph_from_dir(game_dir: str) -> Optional[NarrativeGraph]:
    """Build a NarrativeGraph from a game directory by running the parser."""
    try:
        from vn_parser.renpy_parser  import parse_project
        from graph_builder.graph_builder import build_graph
        script = parse_project(game_dir)
        return build_graph(script)
    except Exception as exc:
        logger.warning("Could not build graph from '%s': %s", game_dir, exc)
        return None
