"""
vn_parser/structure_parser.py
------------------------------
Stage 5 of the parser pipeline.

Converts the flat token stream into structured blocks:

    LabelBlock
        MenuBlock
            ChoiceBlock
        jumps:  List[JumpRef]   ← NEW in v0.2
        calls:  List[CallRef]   ← NEW in v0.2

v0.2 additions
--------------
* ``JumpRef``  — records a ``jump`` target found inside a label's body.
* ``CallRef``  — records a ``call`` target found inside a label's body.

These are collected by the graph builder to construct narrative edges.
The translation-block skip, menu detection, and choice extraction logic
are identical to v0.1.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from .tokenizer import Token, TokenType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Block dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ChoiceBlock:
    text:         str
    indent_level: int
    line_number:  int


@dataclass
class MenuBlock:
    choices:      List[ChoiceBlock] = field(default_factory=list)
    indent_level: int = 0
    line_number:  int = 0
    token_index:  int = 0   # used for context look-back


@dataclass
class JumpRef:
    """A ``jump`` statement inside a label body."""
    target:       str
    line_number:  int


@dataclass
class CallRef:
    """A ``call`` statement inside a label body."""
    target:       str
    line_number:  int


@dataclass
class LabelBlock:
    name:         str
    menus:        List[MenuBlock] = field(default_factory=list)
    jumps:        List[JumpRef]   = field(default_factory=list)   # NEW v0.2
    calls:        List[CallRef]   = field(default_factory=list)   # NEW v0.2
    line_number:  int = 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_structure(tokens: List[Token]) -> List[LabelBlock]:
    """
    Walk the token list and group tokens into LabelBlock → MenuBlock → ChoiceBlock
    hierarchies, also collecting jump/call references per label.

    Args:
        tokens: Ordered list of Token objects from the tokenizer.

    Returns:
        List of LabelBlock objects (one per label found, plus _global if needed).
    """
    labels:        List[LabelBlock]         = []
    current_label: Optional[LabelBlock]     = None

    in_translate_block = False
    translate_indent   = -1

    i = 0
    n = len(tokens)

    while i < n:
        tok = tokens[i]

        # ------------------------------------------------------------------
        # Handle translate blocks
        # ------------------------------------------------------------------
        if tok.token_type == TokenType.TRANSLATE:
            in_translate_block = True
            translate_indent   = tok.indent_level
            i += 1
            continue

        if in_translate_block and tok.indent_level <= translate_indent:
            in_translate_block = False
            translate_indent   = -1
            # fall through — process this token normally

        # ------------------------------------------------------------------
        # LABEL
        # ------------------------------------------------------------------
        if tok.token_type == TokenType.LABEL:
            current_label = LabelBlock(name=tok.value, line_number=tok.line_number)
            labels.append(current_label)
            logger.debug("ln %d: Label '%s'", tok.line_number, tok.value)
            i += 1
            continue

        # ------------------------------------------------------------------
        # JUMP / CALL  (new in v0.2)
        # ------------------------------------------------------------------
        if tok.token_type == TokenType.JUMP and not in_translate_block:
            if current_label is None:
                current_label = LabelBlock(name="_global", line_number=0)
                labels.append(current_label)
            current_label.jumps.append(
                JumpRef(target=tok.value, line_number=tok.line_number)
            )
            i += 1
            continue

        if tok.token_type == TokenType.CALL and not in_translate_block:
            if current_label is None:
                current_label = LabelBlock(name="_global", line_number=0)
                labels.append(current_label)
            current_label.calls.append(
                CallRef(target=tok.value, line_number=tok.line_number)
            )
            i += 1
            continue

        # ------------------------------------------------------------------
        # MENU_START
        # ------------------------------------------------------------------
        if tok.token_type == TokenType.MENU_START:
            if in_translate_block:
                i += 1
                continue

            if current_label is None:
                current_label = LabelBlock(name="_global", line_number=0)
                labels.append(current_label)
                logger.warning(
                    "ln %d: Menu found outside any label; assigning to '_global'.",
                    tok.line_number,
                )

            menu_spaces = tok.leading_spaces

            menu = MenuBlock(
                indent_level=tok.indent_level,
                line_number=tok.line_number,
                token_index=i,
            )
            current_label.menus.append(menu)

            choice_spaces: int = -1
            i += 1

            while i < n:
                inner = tokens[i]

                if inner.leading_spaces <= menu_spaces:
                    if inner.token_type != TokenType.CHOICE_TEXT:
                        break
                    break

                if inner.token_type == TokenType.CHOICE_TEXT:
                    if choice_spaces == -1:
                        choice_spaces = inner.leading_spaces

                    if inner.leading_spaces == choice_spaces:
                        choice = ChoiceBlock(
                            text=inner.value,
                            indent_level=inner.indent_level,
                            line_number=inner.line_number,
                        )
                        menu.choices.append(choice)

                elif inner.token_type == TokenType.MENU_START:
                    break

                elif inner.token_type == TokenType.JUMP and not in_translate_block:
                    # Jumps inside choice bodies still count for the label
                    current_label.jumps.append(
                        JumpRef(target=inner.value, line_number=inner.line_number)
                    )

                elif inner.token_type == TokenType.CALL and not in_translate_block:
                    current_label.calls.append(
                        CallRef(target=inner.value, line_number=inner.line_number)
                    )

                i += 1

            if not menu.choices:
                logger.warning(
                    "ln %d: MenuBlock has no choices — may be caption-only or artefact.",
                    tok.line_number,
                )
            continue  # i already advanced inside inner loop

        i += 1

    total_menus = sum(len(lb.menus) for lb in labels)
    total_jumps = sum(len(lb.jumps) for lb in labels)
    total_calls = sum(len(lb.calls) for lb in labels)
    logger.info(
        "Structure parser: %d label(s), %d menu(s), %d jump(s), %d call(s).",
        len(labels), total_menus, total_jumps, total_calls,
    )
    return labels
