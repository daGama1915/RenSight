"""
vn_parser — Ren'Py Script Parser
---------------------------------
Scans .rpy files and produces a ParsedScript IR.

Public entry point::

    from vn_parser.renpy_parser import parse_project
    script = parse_project("/path/to/game")
"""

from .renpy_parser import parse_project, extract_menus

__all__ = ["parse_project", "extract_menus"]
