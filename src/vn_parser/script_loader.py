"""
script_loader.py
----------------
Stage 2 of the parser pipeline.

Reads a single Ren'Py script file into memory, preserving the original
line order and attaching 1-based line numbers to each line.
"""

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

# A numbered line is a (line_number, raw_text) pair.
NumberedLine = Tuple[int, str]


def load_script(file_path: str, encoding: str = "utf-8") -> List[NumberedLine]:
    """
    Read *file_path* and return a list of (line_number, text) tuples.

    Line numbers are 1-based and match the original file positions so that
    later pipeline stages can report accurate locations for warnings.

    Args:
        file_path: Absolute or relative path to a .rpy script file.
        encoding:  File encoding (default utf-8; fallback latin-1 on error).

    Returns:
        List of (line_number, raw_text) tuples with *no* trailing newlines.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    numbered: List[NumberedLine] = []

    # Attempt UTF-8 first, then fall back to latin-1 for older projects.
    for enc in (encoding, "latin-1"):
        try:
            with open(file_path, "r", encoding=enc) as fh:
                for lineno, text in enumerate(fh, start=1):
                    numbered.append((lineno, text.rstrip("\n")))
            logger.debug("Loaded %d line(s) from '%s' (encoding=%s).",
                         len(numbered), file_path, enc)
            return numbered
        except UnicodeDecodeError:
            logger.warning("Encoding %s failed for '%s', retrying…", enc, file_path)
            numbered = []
        except FileNotFoundError:
            raise

    # If we reach here both encodings failed — return empty and warn.
    logger.error("Could not decode '%s' with any supported encoding.", file_path)
    return []
