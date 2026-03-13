"""
vn_parser/tokenizer.py
----------------------
Stage 4 of the parser pipeline.

Converts each preprocessed line into a typed Token so later stages can
reason about script structure without examining raw text.

v0.2 additions
--------------
Two new token types compared to v0.1:
  JUMP   — ``jump <label>`` statements; value = target label name
  CALL   — ``call <label>`` statements; value = target label name

These are needed by the graph builder to construct narrative edges.

Token types
-----------
LABEL        label <n>:
MENU_START   menu:  (or  menu <n>:)
CHOICE_TEXT  "text":   inside a menu block
DIALOGUE     Any quoted or unquoted narration / character line
JUMP         jump <label>  [from ...]
CALL         call <label>  [from ...]
PYTHON_BLOCK python: / init python:
TRANSLATE    translate <lang> <label>:
UNKNOWN      Anything not matched above
"""

import re
import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Tuple

logger = logging.getLogger(__name__)

NumberedLine = Tuple[int, str]


# ---------------------------------------------------------------------------
# Token type enum
# ---------------------------------------------------------------------------

class TokenType(Enum):
    LABEL        = auto()
    MENU_START   = auto()
    CHOICE_TEXT  = auto()
    DIALOGUE     = auto()
    JUMP         = auto()   # NEW in v0.2
    CALL         = auto()   # NEW in v0.2
    PYTHON_BLOCK = auto()
    TRANSLATE    = auto()
    UNKNOWN      = auto()


# ---------------------------------------------------------------------------
# Token dataclass
# ---------------------------------------------------------------------------

@dataclass
class Token:
    token_type:     TokenType
    value:          str           # Cleaned value (label name, choice text, …)
    raw:            str           # Original line text (for debugging)
    indent_level:   int           # Leading spaces // 4
    leading_spaces: int           # Raw leading-space count
    line_number:    int

    def __repr__(self) -> str:
        return (f"Token({self.token_type.name}, indent={self.indent_level}, "
                f"ln={self.line_number}, value={self.value!r})")


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# label <identifier>:
_LABEL_RE = re.compile(r'^label\s+([A-Za-z_][A-Za-z0-9_]*)\s*:')

# menu:  or  menu <n>:
_MENU_RE  = re.compile(r'^menu\b.*:$')

# python: or init python: or init N python:
_PYTHON_RE = re.compile(r'^(?:init\s+(?:\d+\s+)?)?python\s*:')

# translate <lang> <label>:
_TRANSLATE_RE = re.compile(r'^translate\s+\w+\s+\w+\s*:')

# jump <label>  [from _call_xxx]
_JUMP_RE = re.compile(r'^jump\s+([A-Za-z_][A-Za-z0-9_]*)')

# call <label>  [from _call_xxx]
_CALL_RE = re.compile(r'^call\s+([A-Za-z_][A-Za-z0-9_]*)')

# "text":  or  'text':  → potential choice inside a menu
# Matches:  "text":  OR  "text" if condition:
_CHOICE_RE = re.compile(r'^(["\'])(.+?)\1(?:\s+if\s+.*)?\s*:$')

# A quoted dialogue line (with or without speaker prefix)
_DIALOGUE_QUOTED_RE = re.compile(r'(?:[A-Za-z_]\w*\s+)?["\'].+["\']$')

# Ren'Py / Python keywords that look like bare identifiers but are NOT dialogue.
_RENPY_KEYWORDS = frozenset({
    "jump", "call", "return", "pass", "show", "hide", "scene",
    "play", "stop", "pause", "window", "with", "voice", "queue",
    "nvl", "menu", "label", "image", "define", "default",
    "init", "python", "if", "elif", "else", "for", "while",
    "transform", "style", "screen", "layeredimage",
})


def _leading_spaces(text: str) -> int:
    expanded = text.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(' '))


def _indent_level(spaces: int) -> int:
    return spaces // 4


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def tokenize(numbered_lines: List[NumberedLine]) -> List[Token]:
    """
    Convert a list of (line_number, text) pairs into a list of Tokens.

    Args:
        numbered_lines: Output from preprocessor.preprocess().

    Returns:
        List of Token objects in original line order.
    """
    tokens: List[Token] = []

    for lineno, text in numbered_lines:
        spaces   = _leading_spaces(text)
        level    = _indent_level(spaces)
        stripped = text.strip()

        token = _classify(stripped, text, spaces, level, lineno)
        tokens.append(token)
        logger.debug("  %s", token)

    logger.info("Tokenizer produced %d token(s).", len(tokens))
    return tokens


def _classify(stripped: str, raw: str, spaces: int, level: int, lineno: int) -> Token:
    """Classify a single line and return the appropriate Token."""

    def make(ttype: TokenType, value: str = "") -> Token:
        return Token(
            token_type=ttype,
            value=value,
            raw=raw,
            indent_level=level,
            leading_spaces=spaces,
            line_number=lineno,
        )

    # --- LABEL ---
    m = _LABEL_RE.match(stripped)
    if m:
        return make(TokenType.LABEL, m.group(1))

    # --- TRANSLATE (must come before anything with a colon) ---
    if _TRANSLATE_RE.match(stripped):
        return make(TokenType.TRANSLATE, stripped)

    # --- PYTHON BLOCK ---
    if _PYTHON_RE.match(stripped):
        return make(TokenType.PYTHON_BLOCK, stripped)

    # --- MENU START ---
    if _MENU_RE.match(stripped):
        return make(TokenType.MENU_START)

    # --- JUMP (v0.2) ---
    m = _JUMP_RE.match(stripped)
    if m:
        return make(TokenType.JUMP, m.group(1))

    # --- CALL (v0.2) ---
    m = _CALL_RE.match(stripped)
    if m:
        return make(TokenType.CALL, m.group(1))

    # --- CHOICE TEXT  ("text": at current indent) ---
    m = _CHOICE_RE.match(stripped)
    if m:
        return make(TokenType.CHOICE_TEXT, m.group(2))

    # --- DIALOGUE (quoted lines, with or without speaker) ---
    if _DIALOGUE_QUOTED_RE.match(stripped):
        import re as _re
        q_match = _re.search(r'["\'](.+)["\']$', stripped)
        value = q_match.group(1) if q_match else stripped
        return make(TokenType.DIALOGUE, value)

    # --- DIALOGUE (unquoted narration) ---
    first_word = stripped.split()[0] if stripped.split() else ""
    if (re.match(r'^[A-Za-z_]', stripped)
            and not stripped.endswith(':')
            and first_word not in _RENPY_KEYWORDS):
        return make(TokenType.DIALOGUE, stripped)

    return make(TokenType.UNKNOWN, stripped)
