"""
graph_builder/edge_factory.py
------------------------------
Creates edges in the NarrativeGraph from parsed jump, call, and sequential
relationships.
"""

from __future__ import annotations

from typing import List

from ir.edges           import EdgeType
from ir.narrative_graph import NarrativeGraph
from ir.parsed_script   import ParsedScript


def add_jump_edges(graph: NarrativeGraph, script: ParsedScript) -> None:
    """Add one JUMP edge per jump statement found in the script."""
    for src, dst, file, line in script.jumps:
        graph.add_edge(src, dst,
                       edge_type=EdgeType.JUMP,
                       file=file, line=line)


def add_call_edges(graph: NarrativeGraph, script: ParsedScript) -> None:
    """Add one CALL edge per call statement found in the script."""
    for src, dst, file, line in script.calls:
        graph.add_edge(src, dst,
                       edge_type=EdgeType.CALL,
                       file=file, line=line)


def add_sequential_edges(graph: NarrativeGraph, script: ParsedScript) -> None:
    """
    Add SEQUENTIAL edges between labels that appear consecutively in the
    same source file (i.e. a label falls through to the next one when no
    explicit jump terminates it).

    This mirrors the fall-through logic from v0.1 ``menu_ordering.py`` and
    ensures every label remains reachable in BFS traversal.
    """
    # Group labels by file, in their original insertion order
    from collections import defaultdict
    by_file: dict = defaultdict(list)
    for li in script.labels:
        by_file[li.file].append(li.name)

    for labels_in_file in by_file.values():
        for i in range(len(labels_in_file) - 1):
            src = labels_in_file[i]
            dst = labels_in_file[i + 1]
            # Only add if there isn't already a direct edge
            if not graph.G.has_edge(src, dst):
                graph.add_edge(src, dst, edge_type=EdgeType.SEQUENTIAL)
