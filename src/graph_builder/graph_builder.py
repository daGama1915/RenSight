"""
graph_builder/graph_builder.py
-------------------------------
Converts a ParsedScript IR into a NarrativeGraph.

Pipeline position:

    vn_parser.parse_project()
          ↓ ParsedScript
    graph_builder.build_graph()
          ↓ NarrativeGraph
    exporters / analysis / survey ordering

Usage::

    from graph_builder.graph_builder import build_graph
    from vn_parser.renpy_parser      import parse_project

    script = parse_project("/path/to/game")
    graph  = build_graph(script)
    print(graph)
"""

import logging

from ir.narrative_graph import NarrativeGraph
from ir.parsed_script   import ParsedScript
from .node_factory        import add_label_nodes
from .edge_factory        import add_jump_edges, add_call_edges, add_sequential_edges

logger = logging.getLogger(__name__)


def build_graph(script: ParsedScript) -> NarrativeGraph:
    """
    Construct a NarrativeGraph from a ParsedScript.

    Steps:
      1. Add one node per label.
      2. Add JUMP edges from ``jump`` statements.
      3. Add CALL edges from ``call`` statements.
      4. Add SEQUENTIAL edges between consecutive labels in the same file
         (fall-through links that keep the graph fully connected for BFS).

    Args:
        script: Fully populated ParsedScript from the parser pipeline.

    Returns:
        NarrativeGraph with all nodes and edges populated.
    """
    logger.info("Building narrative graph for %d labels …", script.label_count)

    graph = NarrativeGraph()

    add_label_nodes(graph, script)
    add_jump_edges(graph, script)
    add_call_edges(graph, script)
    add_sequential_edges(graph, script)

    logger.info(
        "Graph complete: %d node(s), %d edge(s), cycles=%s.",
        graph.label_count, graph.edge_count, graph.has_cycles(),
    )
    return graph


def build_graph_from_file(json_path: str) -> NarrativeGraph:
    """
    Convenience loader: read a parsed_script.json and build its graph.

    Handles both v0.2 (full ParsedScript JSON) and v0.1 (menus-only) format.
    """
    import json
    with open(json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    # Distinguish v0.2 from v0.1 by the presence of "labels" key
    if "labels" in data:
        script = ParsedScript.from_dict(data)
    else:
        script = ParsedScript.from_legacy_json(data)

    return build_graph(script)
