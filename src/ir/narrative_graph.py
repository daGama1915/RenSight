"""
ir/narrative_graph.py
---------------------
NarrativeGraph wraps a NetworkX DiGraph and exposes a clean API for
constructing, querying, and exporting the narrative flow graph.

Node conventions
----------------
  * Label nodes  – node ID is the label name string.
  * (Menu data is stored as node attributes on label nodes, not as
    separate NetworkX nodes, keeping the graph simple and traversable.)

Edge conventions
----------------
  * Every edge is label → label.
  * Edge attribute ``edge_type`` holds an EdgeType value string.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import networkx as nx
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "networkx is required for the narrative graph feature.\n"
        "Install it with:  pip install networkx"
    ) from exc

from .edges import EdgeType
from .nodes import NodeType

logger = logging.getLogger(__name__)


class NarrativeGraph:
    """
    Directed graph representing narrative flow between Ren'Py labels.

    The underlying NetworkX DiGraph is accessible as ``NarrativeGraph.G``.

    Quick reference
    ---------------
    Build via NarrativeGraphBuilder, not directly.

    Query::

        ng.has_label("scene03")
        ng.successors("scene03")          # labels reachable from scene03
        ng.predecessors("scene03")        # labels that flow into scene03
        ng.bfs_order(start="start")       # BFS-ordered list of labels
        ng.labels_with_menus()            # labels that contain menus
        ng.is_reachable("start", "end")

    Export::

        ng.to_json()
        ng.to_graphml()
    """

    def __init__(self) -> None:
        self.G: nx.DiGraph = nx.DiGraph()

    # ------------------------------------------------------------------
    # Node management
    # ------------------------------------------------------------------

    def add_label_node(self, name: str, **attrs: Any) -> None:
        """Add or update a label node."""
        self.G.add_node(name, node_type=NodeType.LABEL.value, **attrs)

    def update_node(self, name: str, **attrs: Any) -> None:
        if name in self.G:
            self.G.nodes[name].update(attrs)

    def has_label(self, name: str) -> bool:
        return self.G.has_node(name)

    def node_attrs(self, name: str) -> Dict[str, Any]:
        return dict(self.G.nodes[name]) if self.G.has_node(name) else {}

    # ------------------------------------------------------------------
    # Edge management
    # ------------------------------------------------------------------

    def add_edge(
        self,
        src: str,
        dst: str,
        edge_type: EdgeType = EdgeType.SEQUENTIAL,
        file: str = "",
        line: int = 0,
        choice_text: str = "",
    ) -> None:
        """Add a directed edge, auto-creating missing nodes."""
        if not self.G.has_node(src):
            self.add_label_node(src)
        if not self.G.has_node(dst):
            self.add_label_node(dst)
        self.G.add_edge(
            src, dst,
            edge_type=edge_type.value,
            file=file,
            line=line,
            choice_text=choice_text,
        )

    # ------------------------------------------------------------------
    # Graph metrics
    # ------------------------------------------------------------------

    @property
    def label_count(self) -> int:
        return self.G.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.G.number_of_edges()

    def successors(self, label: str) -> List[str]:
        return list(self.G.successors(label))

    def predecessors(self, label: str) -> List[str]:
        return list(self.G.predecessors(label))

    def all_labels(self) -> List[str]:
        return list(self.G.nodes)

    def labels_with_menus(self) -> List[str]:
        """Return labels whose node attribute menu_ids is non-empty."""
        return [
            n for n in self.G.nodes
            if self.G.nodes[n].get("menu_ids")
        ]

    def is_reachable(self, src: str, dst: str) -> bool:
        if not (self.G.has_node(src) and self.G.has_node(dst)):
            return False
        return nx.has_path(self.G, src, dst)

    def unreachable_from(self, start: str) -> List[str]:
        """Return labels not reachable from *start* via any path."""
        if not self.G.has_node(start):
            return self.all_labels()
        reachable = nx.descendants(self.G, start) | {start}
        return [n for n in self.G.nodes if n not in reachable]

    def has_cycles(self) -> bool:
        return not nx.is_directed_acyclic_graph(self.G)

    def find_cycles(self) -> List[List[str]]:
        try:
            return list(nx.simple_cycles(self.G))
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Traversal orders
    # ------------------------------------------------------------------

    def bfs_order(self, start: str = "start") -> List[str]:
        """
        Return all label nodes in BFS order beginning from *start*.

        Labels unreachable from *start* are appended at the end in
        their original insertion order.
        """
        if not self.G.has_node(start):
            # Fall back to first node in insertion order
            nodes = list(self.G.nodes)
            start = nodes[0] if nodes else start
            if not self.G.has_node(start):
                return list(self.G.nodes)

        visited: List[str] = []
        seen = set()
        queue: deque = deque([start])
        seen.add(start)

        while queue:
            node = queue.popleft()
            visited.append(node)
            for neighbour in self.G.successors(node):
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)

        # Append unreachable nodes
        for node in self.G.nodes:
            if node not in seen:
                visited.append(node)

        return visited

    def dfs_order(self, start: str = "start") -> List[str]:
        """Return all label nodes in DFS pre-order from *start*."""
        if not self.G.has_node(start):
            return list(self.G.nodes)
        visited: List[str] = []
        seen = set()

        def _dfs(n: str) -> None:
            seen.add(n)
            visited.append(n)
            for nb in self.G.successors(n):
                if nb not in seen:
                    _dfs(nb)

        _dfs(start)
        for node in self.G.nodes:
            if node not in seen:
                _dfs(node)
        return visited

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Export graph as a plain JSON-compatible dict."""
        nodes = []
        for n, attrs in self.G.nodes(data=True):
            nodes.append({"id": n, **attrs})

        edges = []
        for src, dst, attrs in self.G.edges(data=True):
            edges.append({"from": src, "to": dst, **attrs})

        return {"nodes": nodes, "edges": edges}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_graphml(self) -> str:
        """Return a GraphML XML string (requires networkx ≥ 2.5)."""
        from io import StringIO
        buf = StringIO()
        nx.write_graphml(self.G, buf)
        return buf.getvalue()

    def to_dot(self) -> str:
        """
        Return a Graphviz DOT string.

        Node shapes encode type:
          * label with menus  → box
          * label without menus → ellipse
        """
        lines = ["digraph NarrativeGraph {", "  rankdir=LR;",
                 "  node [fontname=Helvetica fontsize=10];"]
        for n, attrs in self.G.nodes(data=True):
            has_menus = bool(attrs.get("menu_ids"))
            shape = "box" if has_menus else "ellipse"
            label = n.replace('"', '\\"')
            lines.append(f'  "{label}" [shape={shape}];')
        for src, dst, attrs in self.G.edges(data=True):
            etype = attrs.get("edge_type", "sequential")
            colour = {
                "jump":       "black",
                "call":       "blue",
                "sequential": "gray",
                "choice":     "red",
            }.get(etype, "black")
            src_s = src.replace('"', '\\"')
            dst_s = dst.replace('"', '\\"')
            lines.append(f'  "{src_s}" -> "{dst_s}" [color={colour} label="{etype}"];')
        lines.append("}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (f"NarrativeGraph(nodes={self.label_count}, "
                f"edges={self.edge_count}, "
                f"cycles={self.has_cycles()})")
