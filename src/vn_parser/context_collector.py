"""
context_collector.py
--------------------
Stage 6 of the parser pipeline (runs alongside menu extraction).

For each MenuBlock, looks back through the token stream to find the
N most recent DIALOGUE tokens that appeared before the menu's MENU_START.
These lines give player feedback respondents enough narrative context to
assess the choices meaningfully.
"""

import logging
from typing import List

from .tokenizer import Token, TokenType
from .structure_parser import LabelBlock, MenuBlock

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_LINES = 4   # How many preceding dialogue lines to capture


def collect_context(
    menu: MenuBlock,
    tokens: List[Token],
    max_lines: int = DEFAULT_CONTEXT_LINES,
) -> List[str]:
    """
    Scan backwards from the menu's token position and collect up to
    *max_lines* DIALOGUE token values that appeared before the menu.

    The result is returned in forward (chronological) order so it reads
    naturally in feedback templates.

    Args:
        menu:      MenuBlock whose context we need.
        tokens:    Full token list for the file being parsed.
        max_lines: Maximum number of dialogue lines to capture.

    Returns:
        List of dialogue strings (oldest first), length ≤ max_lines.
    """
    collected: List[str] = []
    start = menu.token_index  # index of the MENU_START token

    # Walk backwards, skipping non-DIALOGUE tokens
    i = start - 1
    while i >= 0 and len(collected) < max_lines:
        tok = tokens[i]
        if tok.token_type == TokenType.DIALOGUE:
            collected.append(tok.value)
        i -= 1

    # Reverse so lines are in forward chronological order
    collected.reverse()
    logger.debug("Menu at ln %d: collected %d context line(s).",
                 menu.line_number, len(collected))
    return collected


def attach_context_to_labels(
    labels: List[LabelBlock],
    tokens: List[Token],
    max_lines: int = DEFAULT_CONTEXT_LINES,
) -> dict:
    """
    Build a mapping of MenuBlock → context lines for all menus across
    all labels.

    Returns:
        Dict mapping id(menu) → List[str] of context lines.
    """
    context_map: dict = {}
    for label in labels:
        for menu in label.menus:
            ctx = collect_context(menu, tokens, max_lines)
            context_map[id(menu)] = ctx
    return context_map
