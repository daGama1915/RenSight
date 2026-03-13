"""
preprocessor.py
---------------
Stage 3 of the parser pipeline.

Cleans raw numbered lines before tokenisation:
  • Strips trailing whitespace
  • Removes blank lines
  • Removes comment-only lines  (lines whose first non-space content is '#')
  • Does NOT strip comments that appear inside quoted strings
"""

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

NumberedLine = Tuple[int, str]

# Matches a line that, after stripping leading whitespace, starts with '#'.
_COMMENT_ONLY_RE = re.compile(r'^\s*#')


def _is_comment_only(text: str) -> bool:
    """Return True if *text* is a pure comment line (not code with inline comment)."""
    return bool(_COMMENT_ONLY_RE.match(text))


def _is_blank(text: str) -> bool:
    return text.strip() == ""


def preprocess(numbered_lines: List[NumberedLine]) -> List[NumberedLine]:
    """
    Apply cleaning transformations to a list of (line_number, text) pairs.

    Blank lines and comment-only lines are dropped.  All other lines have
    their trailing whitespace removed; leading whitespace (indentation) is
    preserved intact so the tokeniser can measure indent levels.

    Args:
        numbered_lines: Raw output from script_loader.load_script().

    Returns:
        Cleaned list of (line_number, text) pairs.
    """
    cleaned: List[NumberedLine] = []
    dropped = 0

    for lineno, text in numbered_lines:
        # Strip trailing whitespace only — keep leading spaces for indentation.
        text = text.rstrip()

        if _is_blank(text):
            dropped += 1
            continue

        if _is_comment_only(text):
            dropped += 1
            logger.debug("Line %d removed (comment): %r", lineno, text)
            continue

        cleaned.append((lineno, text))

    logger.debug("Preprocessor kept %d/%d lines (%d dropped).",
                 len(cleaned), len(cleaned) + dropped, dropped)
    return cleaned
