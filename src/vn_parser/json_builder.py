"""
vn_parser/json_builder.py
--------------------------
Final stage of the vn_parser pipeline.

v0.2 changes vs v0.1
---------------------
* Builds a ``ParsedScript`` IR object instead of a plain dict.
* Collects ``LabelInfo`` entries and jump/call edges.
* ``merge_results`` and ``serialise_to_json`` are retained for backward
  compatibility (CLI export still writes a JSON file).

The canonical output is the ``ParsedScript`` dataclass defined in ``ir/``.
The JSON on disk is the ``ParsedScript.to_dict()`` representation so it can
be trivially reloaded with ``ParsedScript.from_json_file()``.
"""

import json
import logging
import os
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional

from .structure_parser import LabelBlock
from ir.menu         import MenuEntry
from ir.parsed_script import ParsedScript, LabelInfo, NarrativeEdge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Choice ID generation
# ---------------------------------------------------------------------------

def _generate_choice_id(label_name: str, menu_index: int) -> str:
    safe = "".join(c if c.isalnum() or c == '_' else '_' for c in label_name)
    return f"{safe}_menu{menu_index}"


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_parsed_script(
    labels:       List[LabelBlock],
    context_map:  Dict[int, List[str]],
    file_path:    str,
    root_dir:     str,
    game_version: str = "unknown",
) -> ParsedScript:
    """
    Convert structured parse results for a *single* .rpy file into a
    ``ParsedScript`` IR object.

    Args:
        labels:       Parsed label blocks (from structure_parser).
        context_map:  id(menu) → context lines (from context_collector).
        file_path:    Absolute path of the .rpy source file.
        root_dir:     Project root (for relative path construction).
        game_version: Optional version string.

    Returns:
        ParsedScript IR for this file.
    """
    try:
        rel_path = os.path.relpath(file_path, root_dir)
    except ValueError:
        rel_path = file_path

    menus_out:   List[MenuEntry]     = []
    labels_out:  List[LabelInfo]     = []
    jumps_out:   List[NarrativeEdge] = []
    calls_out:   List[NarrativeEdge] = []

    menu_counter: Dict[str, int] = defaultdict(int)

    for label in labels:
        # --- Label record ---
        labels_out.append(LabelInfo(
            name=label.name,
            file=rel_path,
            line=label.line_number,
        ))

        # --- Jump edges ---
        for jref in label.jumps:
            jumps_out.append((label.name, jref.target, rel_path, jref.line_number))

        # --- Call edges ---
        for cref in label.calls:
            calls_out.append((label.name, cref.target, rel_path, cref.line_number))

        # --- Menus ---
        for menu in label.menus:
            if not menu.choices:
                continue

            menu_counter[label.name] += 1
            choice_id = _generate_choice_id(label.name, menu_counter[label.name])
            context   = context_map.get(id(menu), [])
            choices   = [c.text for c in menu.choices]

            entry = MenuEntry(
                choice_id = choice_id,
                file      = rel_path,
                label     = label.name,
                line      = menu.line_number,
                context   = context,
                choices   = choices,
            )
            menus_out.append(entry)

    return ParsedScript(
        game_version    = game_version,
        extraction_date = date.today().isoformat(),
        menus           = menus_out,
        labels          = labels_out,
        jumps           = jumps_out,
        calls           = calls_out,
    )


def merge_scripts(file_scripts: List[ParsedScript]) -> ParsedScript:
    """
    Merge per-file ParsedScript objects into one project-level ParsedScript.
    """
    if not file_scripts:
        return ParsedScript()

    all_menus:  List[MenuEntry]     = []
    all_labels: List[LabelInfo]     = []
    all_jumps:  List[NarrativeEdge] = []
    all_calls:  List[NarrativeEdge] = []
    game_version = "unknown"

    for ps in file_scripts:
        if ps.game_version and ps.game_version != "unknown":
            game_version = ps.game_version
        all_menus.extend(ps.menus)
        all_labels.extend(ps.labels)
        all_jumps.extend(ps.jumps)
        all_calls.extend(ps.calls)

    return ParsedScript(
        game_version    = game_version,
        extraction_date = date.today().isoformat(),
        menus           = all_menus,
        labels          = all_labels,
        jumps           = all_jumps,
        calls           = all_calls,
    )


def serialise_to_json(
    script:      ParsedScript,
    output_path: Optional[str] = None,
    indent:      int = 2,
) -> str:
    """
    Serialise a ParsedScript to JSON, optionally writing to *output_path*.
    """
    json_str = script.to_json(indent=indent)
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(json_str)
        logger.info("Parsed script written to '%s' (%d menus, %d labels).",
                    output_path, script.menu_count, script.label_count)
    return json_str


# ---------------------------------------------------------------------------
# Backward-compatibility shim for v0.1 callers
# ---------------------------------------------------------------------------

def build_json(
    labels:       List[LabelBlock],
    context_map:  Dict[int, List[str]],
    file_path:    str,
    root_dir:     str,
    game_version: str = "unknown",
) -> dict:
    """v0.1 compat: returns a plain dict instead of ParsedScript."""
    ps = build_parsed_script(labels, context_map, file_path, root_dir, game_version)
    return ps.to_dict()


def merge_results(file_results: List[dict]) -> dict:
    """v0.1 compat: merges plain dicts."""
    scripts = [ParsedScript.from_dict(r) for r in file_results]
    return merge_scripts(scripts).to_dict()
