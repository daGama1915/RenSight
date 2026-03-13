"""
ir/parsed_script.py
-------------------
Intermediate representation produced by the parser pipeline.

ParsedScript is the single artefact passed from the ``vn_parser`` package to
every downstream consumer (graph builder, survey exporter, analysis passes).

It contains:
  * all extracted menus
  * all label names (in file-discovery order)
  * all jump edges  (label → target label)
  * all call edges  (label → target label)

Jump vs call distinction is preserved so the graph builder can create
semantically correct edges (calls imply return; jumps do not).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .menu import MenuEntry


# A directed narrative edge: (source_label, target_label, file, line)
NarrativeEdge = Tuple[str, str, str, int]   # src, dst, file, line


@dataclass
class LabelInfo:
    """Lightweight record of a single Ren'Py label's position in source."""
    name:  str
    file:  str
    line:  int


@dataclass
class ParsedScript:
    """
    Full extraction result for an entire Ren'Py project.

    Attributes:
        game_version:     Version string embedded in output (may be "unknown").
        extraction_date:  ISO date string of when the extraction ran.
        menus:            All extracted MenuEntry objects, in file-scan order.
        labels:           All label definitions found, in file-scan order.
        jumps:            ``jump`` statements as (src_label, dst_label, file, line).
        calls:            ``call`` statements as (src_label, dst_label, file, line).
    """

    game_version:     str                  = "unknown"
    extraction_date:  str                  = field(default_factory=lambda: date.today().isoformat())
    menus:            List[MenuEntry]      = field(default_factory=list)
    labels:           List[LabelInfo]      = field(default_factory=list)
    jumps:            List[NarrativeEdge]  = field(default_factory=list)
    calls:            List[NarrativeEdge]  = field(default_factory=list)
    graph:            Optional[Any] = None

    # ------------------------------------------------------------------
    # Convenience queries
    # ------------------------------------------------------------------

    @property
    def label_names(self) -> List[str]:
        """Return all label names in discovery order."""
        return [l.name for l in self.labels]

    @property
    def menu_count(self) -> int:
        return len(self.menus)

    @property
    def label_count(self) -> int:
        return len(self.labels)

    def menus_for_label(self, label: str) -> List[MenuEntry]:
        return [m for m in self.menus if m.label == label]

    def label_info(self, name: str) -> Optional[LabelInfo]:
        for l in self.labels:
            if l.name == name:
                return l
        return None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "game_version":    self.game_version,
            "extraction_date": self.extraction_date,
            "menus": [m.to_dict() for m in self.menus],
            "labels": [
                {"name": l.name, "file": l.file, "line": l.line}
                for l in self.labels
            ],
            "jumps": [
                {"src": e[0], "dst": e[1], "file": e[2], "line": e[3]}
                for e in self.jumps
            ],
            "calls": [
                {"src": e[0], "dst": e[1], "file": e[2], "line": e[3]}
                for e in self.calls
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "ParsedScript":
        menus = [MenuEntry.from_dict(m) for m in data.get("menus", [])]
        labels = [
            LabelInfo(name=l["name"], file=l["file"], line=int(l["line"]))
            for l in data.get("labels", [])
        ]
        jumps = [
            (e["src"], e["dst"], e["file"], int(e["line"]))
            for e in data.get("jumps", [])
        ]
        calls = [
            (e["src"], e["dst"], e["file"], int(e["line"]))
            for e in data.get("calls", [])
        ]
        return cls(
            game_version    = data.get("game_version", "unknown"),
            extraction_date = data.get("extraction_date", date.today().isoformat()),
            menus           = menus,
            labels          = labels,
            jumps           = jumps,
            calls           = calls,
        )

    @classmethod
    def from_json_file(cls, path: str) -> "ParsedScript":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    # Backward-compatible: load a v0.1 menus.json (no labels/jumps/calls)
    @classmethod
    def from_legacy_json(cls, data: dict) -> "ParsedScript":
        """
        Load a v0.1-format JSON dict (menus only, no labels/jumps/calls).
        Creates a minimal ParsedScript with only menu data populated.
        """
        menus = [MenuEntry.from_dict(m) for m in data.get("menus", [])]
        # Infer labels from menu data
        seen: Dict[str, LabelInfo] = {}
        for m in menus:
            if m.label not in seen:
                seen[m.label] = LabelInfo(name=m.label, file=m.file, line=m.line)
        return cls(
            game_version    = data.get("game_version", "unknown"),
            extraction_date = data.get("extraction_date", date.today().isoformat()),
            menus           = menus,
            labels          = list(seen.values()),
        )

    def __repr__(self) -> str:
        return (f"ParsedScript(version={self.game_version!r}, "
                f"labels={self.label_count}, menus={self.menu_count}, "
                f"jumps={len(self.jumps)}, calls={len(self.calls)})")
