"""
graph_builder/node_factory.py
------------------------------
Creates and configures label nodes in the NarrativeGraph.
"""

from __future__ import annotations

from typing import List

from ir.narrative_graph import NarrativeGraph
from ir.parsed_script   import ParsedScript


def add_label_nodes(graph: NarrativeGraph, script: ParsedScript) -> None:
    """
    Add one node per label found in *script*.

    Node attributes set here:
        node_type  – always "label"
        file       – relative source path
        line       – 1-based line number
        menu_ids   – list of choice_id strings whose .label matches this node
        is_entry   – True only for nodes named "start"
    """
    # Build label → [choice_ids] lookup
    menus_by_label: dict[str, List[str]] = {}
    for m in script.menus:
        menus_by_label.setdefault(m.label, []).append(m.choice_id)

    for li in script.labels:
        graph.add_label_node(
            li.name,
            file     = li.file,
            line     = li.line,
            menu_ids = menus_by_label.get(li.name, []),
            is_entry = (li.name == "start"),
        )
