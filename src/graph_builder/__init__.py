"""
graph_builder — Narrative Graph Builder
----------------------------------------
Converts a ParsedScript IR into a NarrativeGraph.

    from graph_builder.graph_builder import build_graph, build_graph_from_file
"""

from .graph_builder import build_graph, build_graph_from_file

__all__ = ["build_graph", "build_graph_from_file"]
