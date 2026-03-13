import re
"""
file_scanner.py
---------------
Stage 1 of the parser pipeline.

Recursively scans a directory for Ren'Py script files (.rpy),
ignoring hidden directories and compiled .rpyc files.
"""

import os
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def scan_for_scripts(root_dir: str) -> List[str]:
    """
    Recursively walk *root_dir* and return a sorted list of absolute
    paths to every .rpy file found.

    Hidden directories (names starting with '.') and compiled .rpyc
    files are silently skipped.

    Args:
        root_dir: Path to the root game directory to scan.

    Returns:
        List of absolute path strings for each .rpy file discovered.

    Raises:
        FileNotFoundError: If root_dir does not exist.
        NotADirectoryError: If root_dir is not a directory.
    """
    root = Path(root_dir).resolve()

    if not root.exists():
        raise FileNotFoundError(f"Directory not found: {root_dir}")
    if not root.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {root_dir}")

    found: List[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune hidden directories in-place so os.walk won't descend into them
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]

        for filename in filenames:
            if filename.endswith('.rpy') and not filename.endswith('.rpyc'):
                full_path = os.path.join(dirpath, filename)
                found.append(full_path)
                logger.debug("Found script: %s", full_path)

    def _nat(p): return [int(c) if c.isdigit() else c.lower()
                          for c in re.split(r"(\d+)", p)]
    found.sort(key=_nat)
    logger.info("File scanner found %d .rpy file(s) under '%s'.", len(found), root_dir)
    return found
