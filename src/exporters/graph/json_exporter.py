"""
exporters/graph/json_exporter.py
---------------------------------
Exports a NarrativeGraph to JSON and GraphML formats.
"""

from __future__ import annotations

import json
import logging
import os

from ir.narrative_graph import NarrativeGraph

logger = logging.getLogger(__name__)


def export_json(
    graph:      NarrativeGraph,
    output_dir: str,
    filename:   str = "narrative_graph.json",
) -> str:
    """Export graph as JSON.  Returns the output file path."""
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(graph.to_json())
    logger.info("Graph JSON written to '%s'.", out_path)
    return out_path


def export_graphml(
    graph:      NarrativeGraph,
    output_dir: str,
    filename:   str = "narrative_graph.graphml",
) -> str:
    """Export graph as GraphML.  Returns the output file path."""
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(graph.to_graphml())
    logger.info("Graph GraphML written to '%s'.", out_path)
    return out_path
