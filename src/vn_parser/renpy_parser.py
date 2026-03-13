"""
vn_parser/renpy_parser.py
--------------------------
Orchestration module for the Ren'Py parser pipeline.

Public entry point for all downstream consumers.  Wires together all stages:

    File Scanner  →  Script Loader  →  Preprocessor  →  Tokenizer
        →  Structure Parser  →  Context Collector  →  JSON Builder

Returns a ``ParsedScript`` IR containing menus, labels, jumps, and calls
extracted from the project.

Typical usage
-------------
    from vn_parser.renpy_parser import parse_project

    script = parse_project(
        game_dir     = "/path/to/vn/game",
        output_path  = "output/parsed_script.json",   # optional
        game_version = "0.4.2",
    )
    print(script.menu_count, "menus found")
"""

import logging
import os
from typing import Optional

from .file_scanner      import scan_for_scripts
from .script_loader     import load_script
from .preprocessor      import preprocess
from .tokenizer         import tokenize
from .structure_parser  import parse_structure
from .context_collector import attach_context_to_labels
from .json_builder      import build_parsed_script, merge_scripts, serialise_to_json
from ir.parsed_script import ParsedScript

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_project(
    game_dir:      str,
    output_path:   Optional[str] = None,
    game_version:  str = "unknown",
    context_lines: int = 4,
    encoding:      str = "utf-8",
) -> ParsedScript:
    """
    Full pipeline: scan *game_dir* for .rpy files, parse them, and return
    a unified ``ParsedScript`` IR.

    Args:
        game_dir:       Root directory of the Ren'Py project (contains .rpy files).
        output_path:    If provided, write the result JSON to this path.
        game_version:   Optional version string embedded in the output.
        context_lines:  Number of preceding dialogue lines to capture per menu.
        encoding:       Source file encoding (default utf-8).

    Returns:
        ParsedScript containing all menus, labels, jumps, and calls found.

    Raises:
        FileNotFoundError: If *game_dir* does not exist.
    """
    logger.info("parse_project: scanning '%s' …", game_dir)

    scripts = scan_for_scripts(game_dir)
    if not scripts:
        logger.warning("No .rpy files found in '%s'.", game_dir)
        return ParsedScript(game_version=game_version)

    per_file: list = []

    for file_path in scripts:
        logger.debug("Processing: %s", file_path)
        try:
            numbered_lines = load_script(file_path, encoding=encoding)
            cleaned        = preprocess(numbered_lines)
            tokens         = tokenize(cleaned)
            labels         = parse_structure(tokens)
            context_map    = attach_context_to_labels(labels, tokens, context_lines)
            ps             = build_parsed_script(
                                labels, context_map, file_path, game_dir, game_version
                             )
            per_file.append(ps)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping '%s' due to error: %s", file_path, exc)

    merged = merge_scripts(per_file)
    merged.game_version = game_version

    if output_path:
        serialise_to_json(merged, output_path)

    logger.info(
        "parse_project complete: %d label(s), %d menu(s), "
        "%d jump(s), %d call(s).",
        merged.label_count, merged.menu_count,
        len(merged.jumps), len(merged.calls),
    )
    return merged


# ---------------------------------------------------------------------------
# Backward-compatibility alias (v0.1 callers used extract_menus)
# ---------------------------------------------------------------------------

def extract_menus(
    game_dir:      str,
    output_path:   Optional[str] = None,
    game_version:  str = "unknown",
    context_lines: int = 4,
    encoding:      str = "utf-8",
) -> dict:
    """
    v0.1 compatibility shim.

    Returns a plain dict with ``game_version``, ``extraction_date``, and
    ``menus`` keys — identical to the v0.1 output format.
    """
    ps = parse_project(game_dir, output_path, game_version, context_lines, encoding)
    return {
        "game_version":    ps.game_version,
        "extraction_date": ps.extraction_date,
        "menus":           [m.to_dict() for m in ps.menus],
    }
