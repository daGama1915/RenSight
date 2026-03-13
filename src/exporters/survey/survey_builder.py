"""
exporters/survey/survey_builder.py
------------------------------------
Survey Generator — converts menus into player-facing feedback templates.

v0.2 entry points
-----------------
    from exporters.survey.survey_builder import generate_surveys

    # From a ParsedScript:
    written = generate_surveys(
        script       = parsed_script,       # ParsedScript IR
        output_dir   = "output/surveys",
        formats      = ["txt", "html"],
        question_sets = ["clarity", "preference"],
    )

    # From a JSON file (v0.1 or v0.2 format):
    written = generate_surveys_from_file(
        json_path    = "output/parsed_script.json",
        output_dir   = "output/surveys",
        formats      = ["html"],
    )

Architecture (unchanged from v0.1)
-----------------------------------
1. Dataset Loader     — load MenuEntry objects from ParsedScript or JSON
2. Template Builder   — assemble TemplateBlock objects
3. Question Generator — attach configurable question sets
4. Format Renderer    — render to TXT / Markdown / CSV / JSON / HTML
5. Export Manager     — write output files to disk
"""

from __future__ import annotations

import csv
import json
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import date
from io import StringIO
from typing import Dict, List, Optional, Sequence, Tuple

from .question_mapper import generate_questions, ALL_QUESTION_SETS
from .menu_ordering   import (
    ALL_ORDER_MODES, ORDER_AS_EXTRACTED,
    sort_nodes, deduplicate_nodes,
)
from ir.menu          import MenuEntry
from ir.parsed_script import ParsedScript
from ir.narrative_graph import NarrativeGraph

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = ("txt", "markdown", "csv", "json", "html")

DEFAULT_INTRO_TEXT = (
    "Thank you for helping improve this visual novel.\n"
    "Read each scene context and available choices, then answer the questions.\n"
    "Your progress is saved automatically \u2014 you can close and reopen this file "
    "and your answers will still be there.\n"
    "When finished, click Save Feedback to download a text file."
)

_DIVIDER_PLAIN = "-" * 50
_DIVIDER_THICK = "=" * 50


# ---------------------------------------------------------------------------
# 1. DATASET LOADER  (accepts ParsedScript or legacy JSON path)
# ---------------------------------------------------------------------------

class DatasetLoadError(ValueError):
    pass


def _nodes_from_script(script: ParsedScript) -> Tuple[List[MenuEntry], dict]:
    menus = [m for m in script.menus if m.is_valid()]
    meta  = {
        "game_version":    script.game_version,
        "extraction_date": script.extraction_date,
    }
    return menus, meta


def load_dataset(json_path: str) -> Tuple[List[MenuEntry], dict]:
    """Load menus from a JSON file (v0.1 or v0.2 format)."""
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"Dataset not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as fh:
        try:
            raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise DatasetLoadError(f"Invalid JSON in '{json_path}': {exc}") from exc

    if not isinstance(raw, dict) or "menus" not in raw:
        raise DatasetLoadError("JSON must contain a top-level 'menus' list.")

    if "labels" in raw:
        script = ParsedScript.from_dict(raw)
    else:
        script = ParsedScript.from_legacy_json(raw)

    return _nodes_from_script(script)


# ---------------------------------------------------------------------------
# 2. TEMPLATE BUILDER
# ---------------------------------------------------------------------------

@dataclass
class TemplateBlock:
    """Fully assembled survey block for one narrative decision point."""
    node:      MenuEntry
    questions: List[str]
    choices:   List[str]   # possibly reordered


def build_templates(
    nodes:             List[MenuEntry],
    questions:         List[str],
    randomise_choices: bool = False,
) -> List[TemplateBlock]:
    blocks: List[TemplateBlock] = []
    for node in nodes:
        choices = list(node.choices)
        if randomise_choices:
            random.shuffle(choices)
        blocks.append(TemplateBlock(
            node=node,
            questions=list(questions),
            choices=choices,
        ))
    return blocks


# ---------------------------------------------------------------------------
# 4. FORMAT RENDERERS
# ---------------------------------------------------------------------------

class RendererBase:
    format_name:    str = "base"
    file_extension: str = "txt"

    def render(self, blocks: List[TemplateBlock], metadata: dict,
               include_context: bool = True) -> str:
        raise NotImplementedError

    def file_name(self) -> str:
        return f"feedback_template.{self.file_extension}"



# ---------------------------------------------------------------------------
# Title helpers
# ---------------------------------------------------------------------------

def _readable_title(choice_id: str) -> str:
    """
    Convert a snake_case / camelCase choice_id to a human-readable title.

    Examples
    --------
    endtiffhouse_menu1    → "End Tiff House — Menu 1"
    scene03_menu12        → "Scene 03 — Menu 12"
    AintSoBad_menu1       → "Aint So Bad — Menu 1"
    barfightbranch_menu2  → "Barfightbranch — Menu 2"
    """
    import re as _re
    m = _re.match(r'^(.*?)_menu(\d+)$', choice_id)
    if m:
        label_part, menu_num = m.group(1), m.group(2)
    else:
        label_part, menu_num = choice_id, None

    # Split camelCase, then on underscores
    s = _re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', label_part)
    s = _re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
    words = [w.capitalize() for part in s.split('_') for w in part.split() if w]
    label_str = ' '.join(words) if words else label_part

    return f"{label_str} \u2014 Menu {menu_num}" if menu_num else label_str


def _readable_file_label(file_path: str) -> str:
    """
    Convert a .rpy file path to a short readable group label.

    Examples
    --------
    game/scripts/day19.rpy        → "Day 19"
    game/scripts/day0events.rpy   → "Day 0 Events"
    game/scripts/eventsalice.rpy  → "Events Alice"
    game/scripts/phoneevents.rpy  → "Phone Events"
    game/events/jake_scene.rpy    → "Jake Scene"
    game/script.rpy               → "Script"
    """
    import re as _re, os as _os
    stem = _os.path.splitext(_os.path.basename(file_path))[0]
    # Split on underscores first
    parts = stem.split('_')
    tokens = []
    # Known narrative keywords to use as split boundaries in compound words
    _BOUNDARIES = ('events', 'event', 'scene', 'scenes', 'chapter', 'day',
                   'prologue', 'epilogue', 'intro', 'outro', 'phone', 'dream',
                   'training', 'gym', 'prison', 'return', 'news', 'world',
                   'zombie', 'hero', 'stone', 'spirit')
    for part in parts:
        # Insert space between letters and digits first
        part = _re.sub(r'([a-zA-Z])(\d)', r'\1 \2', part)
        part = _re.sub(r'(\d)([a-zA-Z])', r'\1 \2', part)
        # Split camelCase
        part = _re.sub(r'([a-z])([A-Z])', r'\1 \2', part)
        # Now try to split compound lowercase words using boundary keywords
        # e.g. "eventsalice" → "events alice", "day0events" → already split above
        # We do a greedy left-to-right boundary match on the lowercase residue
        sub_tokens = part.split()
        expanded = []
        for tok in sub_tokens:
            tl = tok.lower()
            # Try to peel known boundaries from the left
            remaining = tl
            found = []
            while remaining:
                matched = False
                for kw in sorted(_BOUNDARIES, key=len, reverse=True):
                    if remaining.startswith(kw):
                        found.append(kw)
                        remaining = remaining[len(kw):]
                        matched = True
                        break
                if not matched:
                    found.append(remaining)
                    break
            if len(found) > 1:
                expanded.extend(found)
            else:
                expanded.append(tok)
        tokens.extend(expanded)
    words = [w.capitalize() for w in tokens if w]
    return ' '.join(words) if words else file_path

# ---- Plain Text ----

class PlainTextRenderer(RendererBase):
    format_name    = "txt"
    file_extension = "txt"

    def render(self, blocks, metadata, include_context=True) -> str:
        parts = [self._header(metadata)]
        for block in blocks:
            parts.append(self._render_block(block, include_context))
        parts.append(self._footer())
        return "\n".join(parts)

    def _header(self, metadata: dict) -> str:
        intro = metadata.get("intro_text", DEFAULT_INTRO_TEXT)
        intro_lines = [f"  {ln}" for ln in intro.splitlines()]
        return "\n".join([
            _DIVIDER_THICK,
            "  PLAYER FEEDBACK SURVEY",
            f"  Game Version : {metadata.get('game_version', 'unknown')}",
            f"  Generated    : {date.today().isoformat()}",
            _DIVIDER_THICK,
            "",
            *intro_lines,
            "",
        ])

    def _footer(self) -> str:
        return "\n".join([
            _DIVIDER_THICK,
            "  END OF SURVEY",
            "  Please save and return this file when complete.",
            _DIVIDER_THICK,
        ])

    def _render_block(self, block: TemplateBlock, include_context: bool) -> str:
        n     = block.node
        title = _readable_title(n.choice_id)
        out = [
            _DIVIDER_THICK,
            f"  {title}",
            f"  Choice ID : {n.choice_id}",
            f"  Label     : {n.label}",
            f"  File      : {n.file}  (line {n.line})",
            _DIVIDER_THICK,
        ]
        if include_context and n.context:
            out.append("\nContext:")
            for line in n.context:
                out.append(f"  {line}")
        out.append("\nChoices available:")
        for i, choice in enumerate(block.choices, 1):
            out.append(f"  {i}. {choice}")
        out.append("")
        out.append(_DIVIDER_PLAIN)
        out.append("Questions")
        out.append(_DIVIDER_PLAIN)
        for i, q in enumerate(block.questions, 1):
            out.append(f"\n{i}. {q}")
            out.append("   >")
        out.append("\n")
        return "\n".join(out)


# ---- Markdown ----

class MarkdownRenderer(RendererBase):
    format_name    = "markdown"
    file_extension = "md"

    def render(self, blocks, metadata, include_context=True) -> str:
        parts = [self._header(metadata)]
        for block in blocks:
            parts.append(self._render_block(block, include_context))
        return "\n".join(parts)

    def _header(self, metadata: dict) -> str:
        intro = metadata.get("intro_text", DEFAULT_INTRO_TEXT)
        intro_block = "\n".join(f"> {ln}" for ln in intro.splitlines())
        return "\n".join([
            "# Player Feedback Survey",
            "",
            f"**Game Version:** {metadata.get('game_version', 'unknown')}  ",
            f"**Generated:** {date.today().isoformat()}",
            "",
            intro_block,
            "",
            "---",
            "",
        ])

    def _render_block(self, block: TemplateBlock, include_context: bool) -> str:
        n = block.node
        lines = [
            f"## {n.choice_id}",
            "",
            f"**Label:** `{n.label}`   **File:** `{n.file}` — line {n.line}",
            "",
        ]
        if include_context and n.context:
            lines += ["### Context", ""]
            for ctx in n.context:
                lines.append(f"> {ctx}  ")
            lines.append("")
        lines += ["### Choices", ""]
        for i, choice in enumerate(block.choices, 1):
            lines.append(f"{i}. {choice}")
        lines += ["", "### Questions", ""]
        for i, q in enumerate(block.questions, 1):
            lines += [f"**{i}. {q}**", "", "_Your answer:_", ""]
        lines += ["---", ""]
        return "\n".join(lines)


# ---- CSV ----

class CSVRenderer(RendererBase):
    format_name    = "csv"
    file_extension = "csv"

    def render(self, blocks, metadata, include_context=True) -> str:
        buf    = StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
        writer.writerow(["choice_id", "label", "file", "line",
                         "context", "choices", "question", "answer"])
        for block in blocks:
            n           = block.node
            context_str = " | ".join(n.context) if include_context else ""
            choices_str = " | ".join(block.choices)
            for q in block.questions:
                writer.writerow([n.choice_id, n.label, n.file, n.line,
                                 context_str, choices_str, q, ""])
        return buf.getvalue()


# ---- JSON Survey ----

class JSONRenderer(RendererBase):
    format_name    = "json"
    file_extension = "json"

    def render(self, blocks, metadata, include_context=True) -> str:
        survey = {
            "survey_type":  "player_feedback",
            "game_version": metadata.get("game_version", "unknown"),
            "generated":    date.today().isoformat(),
            "sections":     [],
        }
        for block in blocks:
            n = block.node
            section: dict = {
                "choice_id": n.choice_id,
                "label":     n.label,
                "file":      n.file,
                "line":      n.line,
                "choices":   block.choices,
                "questions": [{"question": q, "answer": ""} for q in block.questions],
            }
            if include_context:
                section["context"] = n.context
            survey["sections"].append(section)
        return json.dumps(survey, indent=2, ensure_ascii=False)


# ---- HTML ----

# ---------------------------------------------------------------------------
# HTML grouping mode constants
# ---------------------------------------------------------------------------

HTML_GROUP_FILE     = "file"            # one group per source file (default)
HTML_GROUP_NARRATIVE = "narrative_block" # merge files into day/chapter groups
HTML_GROUP_TOGGLE   = "client_toggle"   # JS button switches between both views
HTML_GROUP_CONFIG   = "config"          # explicit JSON config maps names→files
HTML_GROUP_LABEL    = "label_only"      # file groups with descriptive sub-labels

ALL_HTML_GROUP_MODES = (
    HTML_GROUP_FILE, HTML_GROUP_NARRATIVE, HTML_GROUP_TOGGLE,
    HTML_GROUP_CONFIG, HTML_GROUP_LABEL,
)


def _extract_narrative_group(file_path: str) -> str:
    """
    Extract a narrative group name (day, chapter, arc…) from a file path.

    Rules
    -----
    * Split stem on ``_``.
    * Keep tokens up to and including the first one that contains a digit.
    * Strip trailing letters after the final digit in that token, so
      ``day0events`` → ``day0`` and ``chapter1prologue`` → ``chapter1``.
    * If the stem has no digit at all, fall back to ``_readable_file_label()``.

    Examples
    --------
    game/scripts/day0.rpy      → "Day 0"
    game/scripts/day0events.rpy→ "Day 0"
    game/scripts/day0_events.rpy→"Day 0"
    game/scripts/day12.rpy     → "Day 12"
    game/scripts/day100.rpy    → "Day 100"
    game/scripts/chapter1.rpy  → "Chapter 1"
    game/scripts/chapter1_prologue.rpy → "Chapter 1"
    game/scripts/eventsalice.rpy → "Events Alice"   (no digit → full label)
    game/script.rpy            → "Script"
    """
    import re as _re, os as _os
    stem  = _os.path.splitext(_os.path.basename(file_path))[0]
    parts = stem.split('_')

    key_parts = []
    found_num = False
    for p in parts:
        key_parts.append(p)
        if _re.search(r'\d', p):
            found_num = True
            break

    if not found_num:
        return _readable_file_label(file_path)

    key = '_'.join(key_parts)
    # Strip trailing alphabetic suffix after the last digit: day0events → day0
    key = _re.sub(r'(\d+)[a-zA-Z]+$', r'\1', key)
    # Insert space between letter-digit and digit-letter transitions
    key = _re.sub(r'([a-zA-Z])(\d)', r'\1 \2', key)
    key = _re.sub(r'(\d)([a-zA-Z])', r'\1 \2', key)
    return ' '.join(w.capitalize() for w in key.split() if w)


def _improved_file_label(file_path: str) -> str:
    """
    For Solution E: produce a descriptive label that shows the relation
    between a main file and its companion event/scene files.

    Examples
    --------
    day0.rpy        → "Day 0"
    day0events.rpy  → "Day 0 — Events"
    day0_events.rpy → "Day 0 — Events"
    eventsalice.rpy → "Events — Alice"
    eventsamber.rpy → "Events — Amber"
    script.rpy      → "Script"
    """
    import re as _re, os as _os
    stem  = _os.path.splitext(_os.path.basename(file_path))[0]
    parts = stem.split('_')

    # Find the first numeric-containing part
    num_idx = next((i for i, p in enumerate(parts) if _re.search(r'\d', p)), None)

    if num_idx is None:
        # No number — check for events<name> or <name>events pattern
        m_prefix = _re.match(r'^(events?)([a-zA-Z]+)$', stem, _re.IGNORECASE)
        if m_prefix:
            suffix = m_prefix.group(2).capitalize()
            return f"Events \u2014 {suffix}"
        m_suffix = _re.match(r'^([a-zA-Z]+?)(events?)$', stem, _re.IGNORECASE)
        if m_suffix:
            prefix = m_suffix.group(1).capitalize()
            return f"{prefix} \u2014 Events"
        return _readable_file_label(file_path)

    # Get the key part (numeric part) and any trailing words
    key_raw  = parts[num_idx]
    trailing = parts[num_idx + 1:]

    # Strip trailing alpha from the key: day0events → base=day0, extra=events
    m = _re.match(r'^(.*\d+)([a-zA-Z]*)$', key_raw)
    base_key = m.group(1) if m else key_raw
    inline_suffix = m.group(2) if m else ''

    # Format the base key
    base_key = _re.sub(r'([a-zA-Z])(\d)', r'\1 \2', base_key)
    base_label = ' '.join(w.capitalize() for w in base_key.split() if w)

    # Combine suffix sources
    suffix_words = ([inline_suffix] if inline_suffix else []) + trailing
    if suffix_words:
        suffix_label = ' '.join(w.capitalize() for w in suffix_words if w)
        return f"{base_label} \u2014 {suffix_label}"

    return base_label


def _natural_sort_key(s: str):
    import re as _re
    return [int(c) if c.isdigit() else c.lower() for c in _re.split(r'(\d+)', s)]


class HTMLRenderer(RendererBase):
    """
    Self-contained interactive HTML survey with five grouping strategies:

    file            — one collapsible group per source file  (default)
    narrative_block — merge companion files (day0.rpy + day0events.rpy)
                      into one group by extracting the day/chapter number
    client_toggle   — static HTML; JS button switches between file and
                      narrative-block views on the fly
    config          — developer-supplied JSON maps group names → file lists
    label_only      — file groups with descriptive sub-labels
                      ("Day 0 — Events" instead of "Day 0 Events")

    The grouping strategy is read from ``metadata["html_group_mode"]``.
    For config mode, ``metadata["html_group_config"]`` must be a dict
    with a ``"groups"`` list and an optional ``"fallback"`` key.
    """

    format_name    = "html"
    file_extension = "html"

    def render(self, blocks, metadata, include_context=True) -> str:
        mode   = metadata.get("html_group_mode", HTML_GROUP_FILE)
        config = metadata.get("html_group_config")

        gv           = metadata.get("game_version", "unknown")
        today        = date.today().isoformat()
        total_menus  = len(blocks)                            # unique choice blocks
        total_q      = sum(len(b.questions) for b in blocks)
        intro        = metadata.get("intro_text", DEFAULT_INTRO_TEXT)

        if mode == HTML_GROUP_NARRATIVE:
            body = self._body_narrative(blocks, include_context)
        elif mode == HTML_GROUP_TOGGLE:
            body = self._body_toggle(blocks, include_context, gv)
        elif mode == HTML_GROUP_CONFIG:
            body = self._body_config(blocks, include_context, config)
        elif mode == HTML_GROUP_LABEL:
            body = self._body_label(blocks, include_context)
        else:  # HTML_GROUP_FILE (default)
            body = self._body_file(blocks, include_context)

        return self._page(gv, today, total_menus, total_q, body, intro)

    def file_name(self) -> str:
        return "survey.html"

    # ------------------------------------------------------------------ mode A/B

    def _body_narrative(self, blocks, include_context: bool) -> str:
        """Merge companion files into narrative-day groups."""
        groups: dict = {}
        for b in blocks:
            key = _extract_narrative_group(b.node.file)
            groups.setdefault(key, []).append(b)
        # Sort groups naturally; within each group keep the blocks in their
        # already-sorted order (caller sorted by menu_order).
        sorted_keys = sorted(groups.keys(), key=_natural_sort_key)
        first = sorted_keys[0] if sorted_keys else None
        return "\n".join(
            self._make_group(key, groups[key], key == first, include_context)
            for key in sorted_keys
        )

    # ------------------------------------------------------------------ mode C

    def _body_toggle(self, blocks, include_context: bool, game_version: str) -> str:
        """
        Sections rendered flat with data-file-group / data-narrative-group attrs.
        JS builds whichever view is active and can switch on demand.
        """
        # Render both views independently.
        # The file view uses id_prefix="f-" so that element IDs and
        # textarea ids are unique across the combined HTML document.
        # data-key is kept WITHOUT the prefix so autosave keys are
        # shared between views — answers filled in one view persist
        # when the reader switches to the other.
        narr_groups: dict = {}
        file_groups: dict = {}
        for b in blocks:
            n  = b.node
            ng = _extract_narrative_group(n.file)
            fg = _readable_file_label(n.file)
            narr_html = self._render_section(b, include_context,
                                             extra_data={"narrative-group": ng,
                                                         "file-group":      fg},
                                             id_prefix="")
            file_html = self._render_section(b, include_context,
                                             extra_data={"narrative-group": ng,
                                                         "file-group":      fg},
                                             id_prefix="f-")
            narr_groups.setdefault(ng, []).append((n.line, narr_html))
            file_groups.setdefault(fg, []).append((n.line, file_html))


        def _build_groups(groups_dict, first_key):
            parts = []
            for key in sorted(groups_dict.keys(), key=_natural_sort_key):
                items  = groups_dict[key]
                n      = len(items)
                open_  = " open" if key == first_key else ""
                inner  = "\n".join(h for _, h in items)
                parts.append(
                    f'<details class="file-group"{open_}>\n'
                    f'<summary class="group-header">'
                    f'<span class="group-label">{self._esc(key)}</span>'
                    f'<span class="group-count">{n} choice{"s" if n != 1 else ""}</span>'
                    f'</summary>\n'
                    f'<div class="group-body">\n{inner}\n</div>\n</details>'
                )
            return "\n".join(parts)

        fk = sorted(file_groups.keys(), key=_natural_sort_key)
        nk = sorted(narr_groups.keys(), key=_natural_sort_key)
        file_html = _build_groups(file_groups, fk[0] if fk else "")
        narr_html = _build_groups(narr_groups, nk[0] if nk else "")

        return (
            '<div class="view-toggle-bar">'
            '<span style="font-size:.85rem;color:#666;margin-right:.6rem">Group by:</span>'
            '<button class="view-btn active" id="btn-narr" onclick="switchView(\'narr\')">'
            '&#127760; Narrative block</button>'
            '<button class="view-btn" id="btn-file" onclick="switchView(\'file\')">'
            '&#128196; Source file</button>'
            '</div>\n'
            f'<div id="view-narr">\n{narr_html}\n</div>\n'
            f'<div id="view-file" style="display:none">\n{file_html}\n</div>\n'
            '<script>\n'
            'function switchView(v){\n'
            '  document.getElementById("view-narr").style.display = v==="narr"?"block":"none";\n'
            '  document.getElementById("view-file").style.display = v==="file"?"block":"none";\n'
            '  document.getElementById("btn-narr").classList.toggle("active",v==="narr");\n'
            '  document.getElementById("btn-file").classList.toggle("active",v==="file");\n'
            '}\n'
            '</script>'
        )

    # ------------------------------------------------------------------ mode D

    def _body_config(self, blocks, include_context: bool, config) -> str:
        """Developer-supplied JSON: group names mapped to file lists."""
        if not config or "groups" not in config:
            logger.warning("HTML grouping mode 'config' requires a config dict; "
                           "falling back to narrative_block.")
            return self._body_narrative(blocks, include_context)

        fallback_mode = config.get("fallback", HTML_GROUP_NARRATIVE)

        # Build file → blocks index
        file_index: dict = {}
        for b in blocks:
            file_index.setdefault(b.node.file, []).append(b)

        used_files: set = set()
        group_parts: list = []
        is_first = True

        for grp in config["groups"]:
            name  = grp.get("name", "Unnamed")
            files = grp.get("files", [])
            grp_blocks = []
            for f in files:
                grp_blocks.extend(file_index.get(f, []))
                used_files.add(f)
            if not grp_blocks:
                continue
            group_parts.append(
                self._make_group(name, grp_blocks, is_first, include_context)
            )
            is_first = False

        # Handle any files not covered by config
        leftover = [b for b in blocks if b.node.file not in used_files]
        if leftover:
            if fallback_mode == HTML_GROUP_NARRATIVE:
                leftover_groups: dict = {}
                for b in leftover:
                    k = _extract_narrative_group(b.node.file)
                    leftover_groups.setdefault(k, []).append(b)
                for k in sorted(leftover_groups.keys(), key=_natural_sort_key):
                    group_parts.append(
                        self._make_group(k, leftover_groups[k], False, include_context)
                    )
            else:
                leftover_file: dict = {}
                for b in leftover:
                    k = _readable_file_label(b.node.file)
                    leftover_file.setdefault(k, []).append(b)
                for k in sorted(leftover_file.keys(), key=_natural_sort_key):
                    group_parts.append(
                        self._make_group(k, leftover_file[k], False, include_context)
                    )

        return "\n".join(group_parts)

    # ------------------------------------------------------------------ mode E

    def _body_label(self, blocks, include_context: bool) -> str:
        """File groups with descriptive labels (e.g. 'Day 0 — Events')."""
        groups: dict = {}
        for b in blocks:
            key = _improved_file_label(b.node.file)
            groups.setdefault(key, []).append(b)
        sorted_keys = sorted(groups.keys(), key=_natural_sort_key)
        first = sorted_keys[0] if sorted_keys else None
        return "\n".join(
            self._make_group(key, groups[key], key == first, include_context)
            for key in sorted_keys
        )

    # ------------------------------------------------------------------ mode file (default)

    def _body_file(self, blocks, include_context: bool) -> str:
        groups: dict = {}
        for b in blocks:
            groups.setdefault(b.node.file, []).append(b)
        sorted_files = sorted(groups.keys(), key=_natural_sort_key)
        first = sorted_files[0] if sorted_files else None
        return "\n".join(
            self._make_group(_readable_file_label(f), groups[f],
                             f == first, include_context)
            for f in sorted_files
        )

    # ------------------------------------------------------------------ shared helpers

    def _make_group(self, label: str, blocks, open_by_default: bool,
                    include_context: bool) -> str:
        n     = len(blocks)
        open_ = " open" if open_by_default else ""
        inner = "\n".join(self._render_section(b, include_context) for b in blocks)
        return (
            f'<details class="file-group"{open_}>\n'
            f'<summary class="group-header">'
            f'<span class="group-label">{self._esc(label)}</span>'
            f'<span class="group-count">{n} choice{"s" if n != 1 else ""}</span>'
            f'</summary>\n'
            f'<div class="group-body">\n{inner}\n</div>\n'
            f'</details>'
        )

    def _render_section(self, block, include_context: bool,
                         extra_data: dict = None,
                         id_prefix: str = "") -> str:
        n     = block.node
        raw_sid = n.choice_id.replace(" ", "_")
        sid     = (id_prefix + raw_sid) if id_prefix else raw_sid
        title   = _readable_title(n.choice_id)

        # data-canonical-id is ALWAYS the unprefixed raw_sid so JS can group
        # twin sections in toggle mode (each section appears in both views
        # with different element IDs but the same canonical ID).
        _FIXED = {"file", "line"}
        data_attrs = (f' data-file="{self._esc(n.file)}" data-line="{n.line}"'
                      f' data-canonical-id="{self._esc(raw_sid)}"')
        if extra_data:
            for k, v in extra_data.items():
                if k not in _FIXED:
                    data_attrs += f' data-{k}="{self._esc(str(v))}"'

        html = [
            f'<div class="section" id="{sid}"{data_attrs}>',
            f'  <h3 class="section-title">{self._esc(title)}</h3>',
            f'  <div class="section-meta">'
            f'Choice ID: <code>{self._esc(n.choice_id)}</code> &nbsp;|&nbsp; '
            f'Label: <code>{self._esc(n.label)}</code> &nbsp;|&nbsp; '
            f'<span class="file-ref">{self._esc(n.file)} (line {n.line})</span>'
            f'</div>',
        ]

        if include_context and n.context:
            ctx_items = "\n".join(f'    <p>{self._esc(c)}</p>' for c in n.context)
            html += [
                '  <details class="context-wrap" open>',
                '    <summary>Context</summary>',
                '    <div class="context-block">',
                ctx_items,
                '    </div>',
                '  </details>',
            ]

        html += ['  <h4>Available choices</h4>', '  <ul class="choices-list">']
        for choice in block.choices:
            html.append(f'    <li>{self._esc(choice)}</li>')
        html.append('  </ul>')

        # "I don't remember" skip checkbox — marks the section as reviewed
        # without answering questions, and disables the question area.
        skip_id = f"skip-{sid}"
        html += [
            f'  <label class="skip-label" for="{skip_id}">',
            f'    <input type="checkbox" id="{skip_id}" class="skip-check"'
            f'           onchange="toggleSkip(this)">',
            f'    I don\u2019t remember this scene',
            '  </label>',
        ]

        # Question area — disabled as a unit when skip is checked
        html += ['  <div class="question-area">', '  <h4>Questions</h4>']
        for qi, q in enumerate(block.questions):
            qid = f"{sid}_q{qi}"
            html += [
                '  <div class="question-block">',
                f'    <label for="{qid}">{qi+1}. {self._esc(q)}</label>',
                f'    <textarea id="{qid}" data-key="{raw_sid}_q{qi}"'
                f' placeholder="Your answer\u2026" oninput="autoSave(this)"></textarea>',
                '  </div>',
            ]
        html.append('  </div>')  # .question-area

        html.append('</div>')
        return "\n".join(html)

    @staticmethod
    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # ------------------------------------------------------------------ page wrapper

    @staticmethod
    def _page(game_version: str, today: str, total_menus: int, total_q: int,
              body_html: str, intro_text: str = "") -> str:
        intro_html = "<br>\n  ".join(
            line.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
            for line in (intro_text or DEFAULT_INTRO_TEXT).splitlines()
        )
        gv_safe = game_version.replace("&", "&amp;")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Player Feedback Survey</title>
<style>
/* ── Reset & base ── */
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     max-width:880px;margin:0 auto;padding:1.8rem 1.5rem 7rem;
     background:#f1f5f9;color:#1e293b;line-height:1.7}}

/* ── Page headings ── */
h1{{font-size:1.7rem;font-weight:800;letter-spacing:-.02em;
    border-bottom:3px solid #4f46e5;padding-bottom:.4rem;margin-bottom:.35rem;color:#1e293b}}
h2{{font-size:1.05rem;margin:.25rem 0 .3rem;color:#1e293b;font-weight:700}}
h3.section-title{{font-size:1rem;margin:.25rem 0 .3rem;color:#1e293b;font-weight:700}}
h4{{font-size:.78rem;margin:.9rem 0 .25rem;color:#64748b;font-weight:700;
    text-transform:uppercase;letter-spacing:.06em}}

/* ── Meta bar ── */
.meta-bar{{color:#64748b;font-size:.88rem;margin-bottom:1.1rem}}

/* ── Intro ── */
.intro{{background:#eef2ff;border-left:4px solid #6366f1;padding:.75rem 1.1rem;
        border-radius:0 6px 6px 0;margin-bottom:1.4rem;font-size:.93rem;color:#312e81}}

/* ── Player metadata card ── */
.metadata-card{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;
                 padding:1.3rem 1.5rem;margin-bottom:1.5rem;
                 box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.metadata-card h2{{font-size:1rem;color:#4f46e5;margin-bottom:.2rem}}
.metadata-card p{{font-size:.85rem;color:#64748b;margin-bottom:.9rem}}
.meta-field{{margin-bottom:.85rem}}
.meta-field>label{{font-size:.85rem;font-weight:600;color:#475569;display:block;margin-bottom:.3rem}}
.meta-field input[type="text"]{{
  width:100%;max-width:320px;border:1px solid #cbd5e1;border-radius:5px;
  padding:.35rem .6rem;font-size:.9rem;background:#f8fafc;color:#1e293b;
}}
.meta-field input[type="text"]:focus{{outline:none;border-color:#818cf8;
                                       box-shadow:0 0 0 3px rgba(99,102,241,.15)}}
.meta-radios{{display:flex;flex-wrap:wrap;gap:.5rem .9rem;margin-top:.25rem}}
.meta-radios label{{font-size:.85rem;color:#475569;display:flex;align-items:center;gap:.3rem;cursor:pointer}}
.meta-radios input[type="radio"]{{accent-color:#4f46e5}}

/* ── Progress bar ── */
.progress-wrap{{margin-bottom:1.1rem}}
.progress-label{{font-size:.82rem;color:#64748b;margin-bottom:.3rem;
                  display:flex;justify-content:space-between}}
.progress-bar-outer{{height:7px;background:#e2e8f0;border-radius:4px;overflow:hidden}}
.progress-bar-inner{{height:100%;background:#4f46e5;border-radius:4px;
                      width:0%;transition:width .3s ease}}

/* ── View toggle ── */
.view-toggle-bar{{display:flex;align-items:center;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap}}
.view-btn{{padding:.35rem 1rem;border-radius:6px;border:1px solid #cbd5e1;
           background:#fff;color:#64748b;font-size:.85rem;cursor:pointer;
           transition:background .15s,color .15s,border-color .15s}}
.view-btn:hover{{background:#f1f5f9;border-color:#a5b4fc}}
.view-btn.active{{background:#4f46e5;color:#fff;border-color:#4f46e5}}
.view-btn:focus-visible{{outline:3px solid #818cf8;outline-offset:2px}}

/* ── Collapsible groups ── */
.file-group{{border:1px solid #e2e8f0;border-radius:10px;
             margin-bottom:1rem;overflow:hidden}}
.group-header{{
  display:flex;align-items:center;gap:.7rem;
  padding:.65rem 1.1rem;background:#eef2ff;cursor:pointer;
  font-weight:700;font-size:.97rem;color:#312e81;
  list-style:none;user-select:none;
}}
.group-header::-webkit-details-marker{{display:none}}
.group-header::before{{
  content:"▶";font-size:.65rem;color:#818cf8;
  transition:transform .18s;display:inline-block;flex-shrink:0;
}}
details[open]>.group-header::before{{transform:rotate(90deg)}}
.group-header:focus-visible{{outline:3px solid #818cf8;outline-offset:-2px}}
.group-label{{flex:1}}
.group-count{{background:#c7d2fe;border-radius:10px;padding:1px 9px;
             font-size:.75rem;color:#3730a3;font-weight:700}}
.group-body{{padding:.85rem 1.1rem 1.1rem}}

/* ── Section cards ── */
.section{{border:1px solid #e2e8f0;border-radius:8px;
          padding:1.2rem 1.5rem 1.4rem;margin-bottom:1.4rem;
          background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.05);
          transition:opacity .2s,background .2s}}
.section.skipped{{opacity:.5;background:#f8fafc}}
.section-meta{{font-size:.74rem;color:#64748b;margin-bottom:.3rem;
               word-break:break-all;line-height:1.5}}
.section-meta code{{font-size:.8rem;background:#f1f5f9;
                    border-radius:3px;padding:1px 5px;color:#475569}}
.file-ref{{color:#94a3b8}}

/* ── Collapsible context ── */
details.context-wrap{{margin:.5rem 0 .85rem}}
details.context-wrap summary{{
  font-size:.78rem;font-weight:700;color:#64748b;cursor:pointer;
  text-transform:uppercase;letter-spacing:.06em;
  padding:.2rem 0;user-select:none;list-style:none;display:flex;align-items:center;gap:.35rem;
}}
details.context-wrap summary::-webkit-details-marker{{display:none}}
details.context-wrap summary::before{{
  content:"▶";font-size:.55rem;color:#94a3b8;
  transition:transform .15s;display:inline-block;
}}
details.context-wrap[open] summary::before{{transform:rotate(90deg)}}
details.context-wrap summary:focus-visible{{outline:3px solid #818cf8;outline-offset:2px;border-radius:3px}}
.context-block{{border-left:3px solid #c7d2fe;margin:.4rem 0 0;
                padding:.4rem .85rem;background:#f8fafc;color:#334155;font-style:italic;
                font-size:.9rem}}
.context-block p{{margin:.15rem 0}}

/* ── Choices list ── */
.choices-list{{list-style:disc;padding-left:1.3rem;margin:.3rem 0 .85rem}}
.choices-list li{{margin:.25rem 0;font-size:.93rem}}

/* ── Skip checkbox ── */
.skip-label{{display:inline-flex;align-items:center;gap:.45rem;font-size:.82rem;
             color:#94a3b8;cursor:pointer;margin-bottom:.6rem;user-select:none}}
.skip-label:hover{{color:#64748b}}
.skip-label input[type="checkbox"]{{accent-color:#6366f1;width:14px;height:14px}}

/* ── Question blocks ── */
.question-area{{transition:opacity .2s}}
.section.skipped .question-area{{opacity:.4;pointer-events:none}}
.question-block{{margin-top:.9rem}}
.question-block label{{font-weight:600;display:block;margin-bottom:.25rem;font-size:.92rem;color:#334155}}
.question-block textarea{{
  width:100%;min-height:64px;border:2px solid #e2e8f0;
  border-radius:6px;padding:.45rem .6rem;font-family:inherit;
  font-size:.9rem;resize:vertical;background:#f8fafc;color:#1e293b;
  transition:border-color .15s,box-shadow .15s,background .15s;
}}
/* Focused but not yet answered — blue ring */
.question-block textarea:focus{{
  outline:none;border-color:#818cf8;background:#fff;
  box-shadow:0 0 0 3px rgba(129,140,248,.18);
}}
/* ANSWERED — green border + glow, overrides focus blue for both states */
.question-block textarea.answered{{
  border-color:#16a34a;
  background:#f0fdf4;
}}
.question-block textarea.answered:focus{{
  border-color:#16a34a;
  background:#f0fdf4;
  box-shadow:0 0 0 3px rgba(22,163,74,.18);
}}

/* ── Autosave indicator ── */
#save-indicator{{
  position:fixed;bottom:5.8rem;right:1.5rem;
  font-size:.78rem;color:#16a34a;font-weight:600;
  background:rgba(240,253,244,.97);border:1px solid #86efac;
  padding:.28rem .7rem;border-radius:12px;
  opacity:0;transition:opacity .2s;pointer-events:none;z-index:800;
}}
#save-indicator.visible{{opacity:1}}

/* ── Restore notice ── */
#restore-notice{{background:#ecfdf5;border:1px solid #6ee7b7;border-radius:7px;
                  padding:.55rem 1rem .55rem .85rem;margin-bottom:1.2rem;
                  font-size:.86rem;color:#065f46;display:none;
                  display:none;align-items:center;gap:.6rem}}

/* ── Sticky bottom bar ── */
.save-bar{{position:sticky;bottom:0;background:rgba(241,245,249,.97);
           border-top:1px solid #e2e8f0;padding:.75rem 0;
           display:flex;align-items:center;justify-content:center;
           gap:.9rem;flex-wrap:wrap;z-index:100}}
#progress{{font-size:.83rem;color:#64748b}}
.bar-btn{{padding:.5rem 1.6rem;border:none;border-radius:6px;font-size:.9rem;
          cursor:pointer;transition:background .15s;font-weight:600}}
.bar-btn:focus-visible{{outline:3px solid #818cf8;outline-offset:2px}}
#save-btn{{background:#4f46e5;color:#fff}}
#save-btn:hover{{background:#4338ca}}
#clear-btn{{background:#e2e8f0;color:#475569}}
#clear-btn:hover{{background:#cbd5e1}}
#toast{{display:none;position:fixed;bottom:4.8rem;left:50%;transform:translateX(-50%);
        background:#1e293b;color:#fff;padding:.5rem 1.3rem;border-radius:18px;
        font-size:.85rem;z-index:999;pointer-events:none}}
</style>
</head>
<body>
<h1>Player Feedback Survey</h1>
<p class="meta-bar">
  Game version: <strong>{gv_safe}</strong> &nbsp;|&nbsp;
  Generated: <strong>{today}</strong> &nbsp;|&nbsp;
  Choices: <strong>{total_menus}</strong>
</p>
<div class="intro">{intro_html}</div>
<div id="restore-notice">&#10003;&nbsp;Restored your previous answers from auto-save.
  <button onclick="clearSaved()" style="margin-left:.8rem;background:none;border:none;
    color:#065f46;text-decoration:underline;cursor:pointer;font-size:.86rem">Clear all</button>
</div>

<!-- ── Player metadata ── -->
<div class="metadata-card">
  <h2>About You <span style="font-weight:400;color:#94a3b8">(optional)</span></h2>
  <p>These answers help contextualise your feedback during analysis.</p>

  <div class="meta-field">
    <label for="meta-name">Player name or alias:</label>
    <input type="text" id="meta-name" data-meta-key="name"
           placeholder="Anonymous" oninput="saveMeta(this)">
  </div>

  <div class="meta-field">
    <label>How far did you play?</label>
    <div class="meta-radios">
      <label><input type="radio" name="play_depth" data-meta-key="play_depth" value="early"     onchange="saveMeta(this)"> Early game</label>
      <label><input type="radio" name="play_depth" data-meta-key="play_depth" value="mid"       onchange="saveMeta(this)"> Mid game</label>
      <label><input type="radio" name="play_depth" data-meta-key="play_depth" value="late"      onchange="saveMeta(this)"> Late game</label>
      <label><input type="radio" name="play_depth" data-meta-key="play_depth" value="completed" onchange="saveMeta(this)"> Completed</label>
    </div>
  </div>

  <div class="meta-field">
    <label>Playthroughs?</label>
    <div class="meta-radios">
      <label><input type="radio" name="play_count" data-meta-key="play_count" value="1"   onchange="saveMeta(this)"> First</label>
      <label><input type="radio" name="play_count" data-meta-key="play_count" value="2-3" onchange="saveMeta(this)"> 2\u20133</label>
      <label><input type="radio" name="play_count" data-meta-key="play_count" value="4+"  onchange="saveMeta(this)"> 4+</label>
    </div>
  </div>
</div>

<!-- ── Progress bar ── -->
<div class="progress-wrap" aria-live="polite">
  <div class="progress-label">
    <span id="progress-text">0 / {total_menus} choices reviewed</span>
    <span id="progress-pct">0%</span>
  </div>
  <div class="progress-bar-outer" role="progressbar"
       aria-valuemin="0" aria-valuemax="{total_menus}" aria-valuenow="0" id="progress-bar">
    <div class="progress-bar-inner" id="progress-fill"></div>
  </div>
</div>

{body_html}

<div class="save-bar">
  <span id="progress">0 / {total_menus} choices reviewed</span>
  <button class="bar-btn" id="save-btn"  onclick="saveFeedback()">&#128190; Save Feedback</button>
  <button class="bar-btn" id="clear-btn" onclick="clearSaved()">&#10005; Clear saved data</button>
</div>
<div id="save-indicator">&#10003; Saved</div>
<div id="toast"></div>

<script>
const STORE_PFX    = "vn_survey__{gv_safe}__";
const TOTAL_MENUS  = {total_menus};

// ── Debounced autosave ────────────────────────────────────────────────────────
const _saveTimers = {{}};
function autoSave(ta) {{
  const key = ta.dataset.key;
  clearTimeout(_saveTimers[key]);
  markAnswered(ta);     // visual feedback: immediate
  syncTwins(ta);        // keep the other view's textarea in sync
  updateProgress();
  _saveTimers[key] = setTimeout(function() {{
    try {{
      localStorage.setItem(STORE_PFX + key, ta.value);
      showSaveIndicator();
    }} catch(e) {{ console.warn("autosave failed:", e); }}
  }}, 500);
}}

function markAnswered(ta) {{
  ta.classList.toggle("answered", ta.value.trim().length > 0);
}}

// Sync twin textareas (toggle mode has two per question — one per view).
// Keeps values consistent when the reader switches views.
function syncTwins(ta) {{
  const key = ta.dataset.key;
  document.querySelectorAll('textarea[data-key="' + key + '"]').forEach(function(t) {{
    if (t !== ta) {{ t.value = ta.value; markAnswered(t); }}
  }});
}}

// ── Autosave indicator ────────────────────────────────────────────────────────
let _siTimer;
function showSaveIndicator() {{
  const el = document.getElementById("save-indicator");
  if (!el) return;
  el.classList.add("visible");
  clearTimeout(_siTimer);
  _siTimer = setTimeout(function() {{ el.classList.remove("visible"); }}, 1600);
}}

// ── Skip checkbox ─────────────────────────────────────────────────────────────
// Marks a section as reviewed without answering, dims it, disables its textareas.
function toggleSkip(cb) {{
  const section = cb.closest(".section");
  const canId   = section.dataset.canonicalId;
  const isSkip  = cb.checked;
  // Apply to ALL sections sharing this canonical ID (toggle-mode twins)
  document.querySelectorAll('.section[data-canonical-id="' + canId + '"]')
    .forEach(function(sec) {{
      sec.classList.toggle("skipped", isSkip);
      // Keep twin checkboxes in sync
      const twin = sec.querySelector(".skip-check");
      if (twin && twin !== cb) twin.checked = isSkip;
    }});
  try {{
    localStorage.setItem(STORE_PFX + "skip__" + canId, isSkip ? "1" : "");
  }} catch(e) {{}}
  updateProgress();
}}

// ── Metadata save ─────────────────────────────────────────────────────────────
function saveMeta(el) {{
  try {{ localStorage.setItem(STORE_PFX + "meta__" + el.dataset.metaKey, el.value); }}
  catch(e) {{}}
}}

// ── Restore on load ───────────────────────────────────────────────────────────
function restoreAnswers() {{
  let restored = 0;
  const seenKeys = new Set();
  // Textareas — deduplicate by data-key so toggle twins aren't double-counted
  document.querySelectorAll("textarea[data-key]").forEach(function(ta) {{
    const key = ta.dataset.key;
    const v   = localStorage.getItem(STORE_PFX + key);
    if (v) {{
      ta.value = v;
      markAnswered(ta);
      if (!seenKeys.has(key)) {{ seenKeys.add(key); restored++; }}
    }}
  }});
  // Skip states
  document.querySelectorAll(".section[data-canonical-id]").forEach(function(sec) {{
    const canId = sec.dataset.canonicalId;
    if (localStorage.getItem(STORE_PFX + "skip__" + canId) === "1") {{
      const cb = sec.querySelector(".skip-check");
      if (cb && !cb.checked) {{ cb.checked = true; toggleSkip(cb); }}
    }}
  }});
  // Player metadata
  document.querySelectorAll("[data-meta-key]").forEach(function(el) {{
    const v = localStorage.getItem(STORE_PFX + "meta__" + el.dataset.metaKey);
    if (v !== null) {{
      if (el.type === "radio") {{ el.checked = (el.value === v); }}
      else                     {{ el.value   = v; }}
    }}
  }});
  if (restored > 0 || document.querySelector(".section.skipped")) {{
    const rn = document.getElementById("restore-notice");
    if (rn) rn.style.display = "flex";
  }}
  updateProgress();
}}

// ── Progress (menu-based) ─────────────────────────────────────────────────────
// A choice is "reviewed" when: at least one textarea is answered OR skip is checked.
// Deduplicates by data-canonical-id so toggle-mode twins aren't double-counted.
function updateProgress() {{
  const seen     = new Set();
  let   reviewed = 0;
  document.querySelectorAll(".section[data-canonical-id]").forEach(function(sec) {{
    const cid = sec.dataset.canonicalId;
    if (seen.has(cid)) return;
    seen.add(cid);
    const skipped   = sec.classList.contains("skipped");
    const hasAnswer = sec.querySelector("textarea.answered") !== null;
    if (skipped || hasAnswer) reviewed++;
  }});
  const total = seen.size;
  const pct   = total > 0 ? Math.round(reviewed / total * 100) : 0;
  const txt   = reviewed + " / " + total + " choices reviewed";
  ["progress","progress-text"].forEach(function(id) {{
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
  }});
  const pp = document.getElementById("progress-pct");
  const pf = document.getElementById("progress-fill");
  const pb = document.getElementById("progress-bar");
  if (pp) pp.textContent = pct + "%";
  if (pf) pf.style.width = pct + "%";
  if (pb) {{ pb.setAttribute("aria-valuenow", reviewed);
             pb.setAttribute("aria-valuetext", txt); }}
}}

// ── Clear saved data ──────────────────────────────────────────────────────────
function clearSaved() {{
  if (!confirm("Clear all auto-saved answers for this survey? This cannot be undone.")) return;
  document.querySelectorAll("textarea[data-key]").forEach(function(ta) {{
    localStorage.removeItem(STORE_PFX + ta.dataset.key);
    ta.value = "";
    ta.classList.remove("answered");
  }});
  document.querySelectorAll(".section[data-canonical-id]").forEach(function(sec) {{
    localStorage.removeItem(STORE_PFX + "skip__" + sec.dataset.canonicalId);
    sec.classList.remove("skipped");
    const cb = sec.querySelector(".skip-check");
    if (cb) cb.checked = false;
  }});
  document.querySelectorAll("[data-meta-key]").forEach(function(el) {{
    localStorage.removeItem(STORE_PFX + "meta__" + el.dataset.metaKey);
    if (el.type === "radio") el.checked = false;
    else el.value = "";
  }});
  const rn = document.getElementById("restore-notice");
  if (rn) rn.style.display = "none";
  updateProgress();
  toast("Auto-save cleared.");
}}

// ── View toggle ───────────────────────────────────────────────────────────────
function switchView(v) {{
  document.getElementById("view-narr").style.display = v === "narr" ? "block" : "none";
  document.getElementById("view-file").style.display = v === "file" ? "block" : "none";
  document.getElementById("btn-narr").classList.toggle("active", v === "narr");
  document.getElementById("btn-file").classList.toggle("active", v === "file");
}}

// ── Export to TXT ─────────────────────────────────────────────────────────────
function saveFeedback() {{
  var D = "=".repeat(56);
  var d = "-".repeat(56);
  var lines = [D, "  PLAYER FEEDBACK RESPONSES",
    "  Game: {gv_safe}  |  Saved: " + new Date().toLocaleString(), D];

  // Player metadata
  lines.push("", "  PLAYER INFORMATION", d);
  document.querySelectorAll("[data-meta-key]").forEach(function(el) {{
    if ((el.type === "radio" && el.checked) || el.type === "text") {{
      lines.push("  " + el.dataset.metaKey + ": " + el.value);
    }}
  }});

  // Determine active view (in toggle mode, export only the visible one)
  var visibleView = null;
  var vn = document.getElementById("view-narr");
  var vf = document.getElementById("view-file");
  if (vn && vf) visibleView = (vf.style.display === "none") ? vn : vf;
  var root = visibleView || document;

  root.querySelectorAll(".file-group").forEach(function(grp) {{
    var lbl = grp.querySelector(".group-label");
    if (lbl) {{ lines.push("", ">>> " + lbl.textContent.trim()); }}
    grp.querySelectorAll(".section").forEach(function(sec) {{
      var h3   = sec.querySelector("h3.section-title");
      var meta = sec.querySelector(".section-meta");
      lines.push("", d);
      if (h3)   lines.push("  " + h3.textContent.trim());
      if (meta) lines.push("  " + meta.textContent.replace(/[ \t\n\r]+/g," ").trim());
      lines.push(d);
      // Skip flag
      var cb = sec.querySelector(".skip-check");
      if (cb && cb.checked) {{ lines.push("  [SKIPPED — player does not remember this scene]"); return; }}
      // Context
      sec.querySelectorAll(".context-block p").forEach(function(p) {{
        lines.push("  " + p.textContent.trim());
      }});
      // Answers
      sec.querySelectorAll(".question-block").forEach(function(qb, qi) {{
        var lbl2 = qb.querySelector("label");
        var ta   = qb.querySelector("textarea");
        lines.push("");
        lines.push((qi+1) + ". " + (lbl2 ? lbl2.textContent.trim() : ""));
        lines.push("   > " + (ta && ta.value.trim() ? ta.value.trim() : "(no answer)"));
      }});
    }});
  }});
  lines.push("", D);

  var blob = new Blob([lines.join("\\n")], {{type:"text/plain;charset=utf-8"}});
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "feedback_responses.txt";
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  toast("Saved! Check your downloads.");
}}

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg) {{
  var t = document.getElementById("toast");
  t.textContent = msg; t.style.display = "block";
  setTimeout(function() {{ t.style.display = "none"; }}, 2800);
}}

document.addEventListener("DOMContentLoaded", restoreAnswers);
</script>
</body>
</html>"""



# ---------------------------------------------------------------------------
# Renderer registry
# ---------------------------------------------------------------------------

_RENDERERS: Dict[str, RendererBase] = {
    "txt":      PlainTextRenderer(),
    "markdown": MarkdownRenderer(),
    "csv":      CSVRenderer(),
    "json":     JSONRenderer(),
    "html":     HTMLRenderer(),
}

_FORMAT_FILE_NAMES = {
    "txt":      "feedback_template.txt",
    "markdown": "feedback_template.md",
    "csv":      "survey_dataset.csv",
    "json":     "survey_questions.json",
    "html":     "survey.html",
}


# ---------------------------------------------------------------------------
# 5. EXPORT MANAGER
# ---------------------------------------------------------------------------

def export_surveys(
    blocks:          List[TemplateBlock],
    metadata:        dict,
    output_dir:      str,
    formats:         Sequence[str],
    include_context: bool = True,
    intro_text:      Optional[str] = None,
    base_name:       Optional[str] = None,
) -> Dict[str, str]:
    """
    Write rendered survey templates to disk.  Returns {format: path}.

    Args:
        base_name: Optional stem for output filenames.  When supplied,
                   every format uses ``<base_name>.<ext>`` instead of the
                   built-in defaults (e.g. "feedback_template.txt").
    """
    os.makedirs(output_dir, exist_ok=True)
    written: Dict[str, str] = {}

    # Sanitise base_name once: strip path separators and leading dots.
    import re as _re
    _bn = _re.sub(r'[/\\\\:*?"<>|]', "_", base_name.strip()).strip(".")\
          if base_name and base_name.strip() else None

    # Extension map for formats that have non-obvious extensions
    _EXT = {"txt": "txt", "markdown": "md", "csv": "csv",
            "json": "json", "html": "html"}

    for fmt in formats:
        fmt      = fmt.lower().strip()
        renderer = _RENDERERS.get(fmt)
        if renderer is None:
            logger.warning("Unknown format '%s' — skipping.", fmt)
            continue
        _meta = {**metadata}
        if intro_text is not None:
            _meta["intro_text"] = intro_text
        content   = renderer.render(blocks, _meta, include_context)
        if _bn:
            ext       = _EXT.get(fmt, fmt)
            file_name = f"{_bn}.{ext}"
        else:
            file_name = _FORMAT_FILE_NAMES.get(fmt, f"survey.{fmt}")
        out_path  = os.path.join(output_dir, file_name)
        newline   = "" if fmt == "csv" else "\n"
        with open(out_path, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(content)
        written[fmt] = out_path
        logger.info("Exported %-10s → %s", fmt, out_path)

    return written


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def generate_surveys(
    script:            ParsedScript,
    output_dir:        str = "output/surveys",
    formats:           Sequence[str] = ("txt", "html"),
    question_sets:     Optional[Sequence[str]] = None,
    include_context:   bool = True,
    randomise_choices: bool = False,
    menu_order:        str  = ORDER_AS_EXTRACTED,
    graph:             Optional[NarrativeGraph] = None,
    game_dir:          Optional[str] = None,
    remove_duplicates: bool = True,
    intro_text:        Optional[str] = None,
    html_group_mode:   str            = "file",
    html_group_config: Optional[dict] = None,
    base_name:         Optional[str]  = None,
) -> Dict[str, str]:
    """
    Full pipeline: ParsedScript → survey files on disk.

    Args:
        script:            Source data (ParsedScript IR).
        output_dir:        Directory to write output files.
        formats:           Format names, e.g. ("txt", "html").
        question_sets:     Which question sets to include (None = all).
        include_context:   Include dialogue context lines in output.
        randomise_choices: Shuffle choice order in each block.
        menu_order:        One of ALL_ORDER_MODES.
        graph:             Pre-built NarrativeGraph for narrative_flow order.
        game_dir:          Game directory (used if graph is None and mode=narrative_flow).
        remove_duplicates: Remove exact-duplicate menus before rendering.

    Returns:
        Dict mapping format name → output file path.
    """
    nodes, metadata = _nodes_from_script(script)
    if intro_text is not None:
        metadata["intro_text"] = intro_text
    metadata["html_group_mode"]   = html_group_mode
    metadata["html_group_config"] = html_group_config

    if remove_duplicates:
        nodes, n_removed = deduplicate_nodes(nodes)
        if n_removed:
            logger.info("Removed %d duplicate menu(s).", n_removed)

    nodes = sort_nodes(nodes, mode=menu_order, graph=graph, game_dir=game_dir)

    questions = generate_questions(question_sets)
    blocks    = build_templates(nodes, questions, randomise_choices)

    logger.info(
        "Generating surveys: %d menu(s), %d question(s)/menu, formats=%s",
        len(blocks), len(questions), list(formats),
    )

    return export_surveys(blocks, metadata, output_dir, formats,
                          include_context, intro_text=intro_text,
                          base_name=base_name)


def generate_surveys_from_file(
    json_path:         str,
    output_dir:        str = "output/surveys",
    formats:           Sequence[str] = ("txt", "html"),
    question_sets:     Optional[Sequence[str]] = None,
    include_context:   bool = True,
    randomise_choices: bool = False,
    menu_order:        str  = ORDER_AS_EXTRACTED,
    game_dir:          Optional[str] = None,
    remove_duplicates: bool = True,
    graph_path:        Optional[str] = None,
    intro_text:        Optional[str] = None,
    html_group_mode:   str            = "file",
    html_group_config: Optional[dict] = None,
    base_name:         Optional[str]  = None,
) -> Dict[str, str]:
    """
    Convenience wrapper: load a JSON file, then call ``generate_surveys()``.
    """
    nodes, _meta = load_dataset(json_path)
    
    # <-- NEW: Load the graph if the user provides it
    graph_obj = None
    if graph_path and os.path.exists(graph_path):
        try:
            from ir.narrative_graph import NarrativeGraph # Adjust import as needed
            with open(graph_path, "r", encoding="utf-8") as f:
                graph_data = json.load(f)
                # Assuming NarrativeGraph can be instantiated from a dict
                graph_obj = NarrativeGraph.from_json(graph_data) 
        except Exception as e:
            logger.error(f"Failed to load narrative graph: {e}")

    # Wrap in a minimal ParsedScript for the main function
    script = ParsedScript(
        game_version    = _meta.get("game_version", "unknown"),
        extraction_date = _meta.get("extraction_date", ""),
        menus           = nodes,
        graph           = graph_obj, # <-- NEW: Attach it to the script
    )
    
    return generate_surveys(
        script            = script,
        output_dir        = output_dir,
        formats           = formats,
        question_sets     = question_sets,
        include_context   = include_context,
        randomise_choices = randomise_choices,
        menu_order        = menu_order,
        remove_duplicates  = remove_duplicates,
        intro_text         = intro_text,
        html_group_mode    = html_group_mode,
        html_group_config  = html_group_config,
        base_name          = base_name,
    )