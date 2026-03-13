"""
gui/rensight_gui.py
-------------------
Graphical user interface for Ren'Sight v0.2.2-alpha.

Tabs
----
  Tab 0 — Auto Pilot         (one-click: Parse → Graph → Survey, using saved defaults)
  Tab 1 — Game Parser       (parse .rpy → parsed_script.json)
  Tab 2 — Narrative Graph    (graph_builder → graph export + BFS stats)
  Tab 3 — Survey Generator   (survey_builder → survey files)
  Tab 4 — Feedback Analyser  (stub — coming in v0.3)
  Tab 5 — Settings           (persist Auto Pilot defaults to rensight_config.json)

Design
------
  * Modern ttk "clam" theme with a custom indigo/slate palette
  * Every tab is wrapped in a scrollable canvas so content is never clipped
  * ScrollableFrame uses a class-level focus guard instead of unconditional
    bind_all, preventing inter-frame scroll conflicts when multiple scrollable
    areas exist in the same window
  * All long-running operations run in daemon threads via _run_in_thread,
    which automatically manages the status bar and progress indicator
  * A dark log panel at the bottom receives all Python log records
  * Window taskbar icon is loaded from gui/icon.png; the embedded base64
    image is used as a fallback if the file is not found
  * User-configurable Auto Pilot defaults are saved to rensight_config.json
    next to this file; missing keys fall back to DEFAULT_CONFIG at runtime

Changes in v0.2.2
-----------------
  * Renamed "Dashboard" tab to "Auto Pilot"
  * Added Tab 5 Settings with persistent config (rensight_config.json)
  * Auto Pilot graph defaults changed to JSON + Interactive HTML
  * Icon loaded from gui/icon.png with base64 fallback
  * ScrollableFrame: replaced unconditional bind_all with a class-level
    _focused guard; avoids unexpected scroll behaviour with multiple frames
  * Fixed: _on_group_mode_change() called on tab build to sync the config-file
    picker visibility with the initial radio-button state
  * Fixed: browse cancel no longer wipes the entry (_safe_browse helper)
  * Fixed: inline lambda on group-config Browse had the same cancel bug
  * Added persistent status bar + indeterminate progress bar
  * Added _Tooltip helper; applied to non-obvious UI options
  * Added Ctrl+R keyboard shortcut (runs the active tab's primary action)
  * Consistent per-exporter error handling: one failed format logs a warning
    and continues rather than aborting the whole run
  * Removed the unused self._parsed_script_path field
  * Added alpha-version disclaimer popup on first launch
"""

from __future__ import annotations

import base64
import importlib
import json
import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------

_GUI_DIR   = os.path.dirname(os.path.abspath(__file__))
_TOOL_ROOT = os.path.dirname(_GUI_DIR)
_SRC_DIR   = os.path.join(_TOOL_ROOT, "src")
for _p in (_TOOL_ROOT, _SRC_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persistent configuration
# ---------------------------------------------------------------------------

# Config file lives next to this module so it travels with the project
_CONFIG_PATH = os.path.join(_GUI_DIR, "rensight_config.json")

# All Auto Pilot defaults.  New keys added in future versions will always be
# present in the runtime dict because _load_config merges from this reference.
DEFAULT_CONFIG: Dict[str, Any] = {
    # Parser settings
    "auto_game_version":    "unknown",
    "auto_context_lines":   4,
    # Graph export toggles
    "auto_graph_json":      True,
    "auto_graph_dot":       False,
    "auto_graph_png":       False,
    "auto_graph_svg":       False,
    "auto_graph_html":      True,
    # Survey output formats
    "auto_fmt_txt":         False,
    "auto_fmt_html":        True,
    "auto_fmt_markdown":    False,
    "auto_fmt_csv":         False,
    "auto_fmt_json":        False,
    # Question-set toggles (True = selected)
    "auto_qs_clarity":                  True,
    "auto_qs_preference":               True,
    "auto_qs_narrative_impact":         True,
    "auto_qs_moral_tension":            False,
    "auto_qs_writing_quality":          False,
    "auto_qs_character_expression":     False,
    "auto_qs_consequence_anticipation": False,
    "auto_qs_agency_and_control":       False,
    "auto_qs_emotional_resonance":      False,
    "auto_qs_replayability":            False,
    "auto_qs_context_and_pacing":       False,
    # Survey misc
    "auto_menu_order":          "as_extracted",
    "auto_html_group":          "narrative_block",
    "auto_include_context":     True,
    "auto_randomise_choices":   False,
    "auto_remove_duplicates":   True,
    # Output
    "auto_output_folder":   "rensight_output",
}

# All question-set identifiers in display order
_ALL_QUESTION_SETS: tuple = (
    "clarity", "preference", "narrative_impact", "moral_tension",
    "writing_quality", "character_expression", "consequence_anticipation",
    "agency_and_control", "emotional_resonance", "replayability",
    "context_and_pacing",
)


def _load_config() -> Dict[str, Any]:
    """
    Load user settings from _CONFIG_PATH and merge with DEFAULT_CONFIG.

    The merge strategy ensures the returned dict is always fully populated:
    any key present in DEFAULT_CONFIG but absent from the stored file
    (e.g. after a version upgrade) is filled in with its default value.
    Returns a fresh copy of DEFAULT_CONFIG if the file is absent or corrupt.
    """
    cfg = dict(DEFAULT_CONFIG)   # start with a complete copy of all defaults
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            stored = json.load(fh)
        # Accept only keys that exist in DEFAULT_CONFIG; ignore unknown keys
        for key in DEFAULT_CONFIG:
            if key in stored:
                cfg[key] = stored[key]
    except FileNotFoundError:
        pass   # first run — silently use defaults
    except Exception as exc:
        logger.warning("Could not load config (%s); falling back to defaults.", exc)
    return cfg


def _save_config(cfg: Dict[str, Any]) -> None:
    """
    Persist cfg to _CONFIG_PATH as human-readable JSON.
    Logs a warning and returns silently if the write fails.
    """
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Could not save config: %s", exc)


# ---------------------------------------------------------------------------
# App icon  (32×32 indigo book, embedded as base64 PNG fallback)
# ---------------------------------------------------------------------------

_ICON_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAgklEQVR42mNgwAL83Z7+pwVmwAdoZSlR"
    "jqG35RiOGNkOGCjL4Y4YdQA+SSD4QAiTo3boOYCQGnL0jTqA6mlgQBxASciR5QBi8zZN0gAphtIsER"
    "JrME1zAbE5g6bZkO6JkJpyVC2IyA0hqpaEAxoCNHfAaIto2LeMRzsmg6dzOpDdcwA90DL3vtHsCAAAA"
    "AABJRkJggg=="
)


def _set_icon(root: tk.Tk) -> None:
    # Prefer an external file so designers can swap the icon without code changes
    icon_file = os.path.join(_GUI_DIR, "icon.png")
    try:
        if os.path.isfile(icon_file):
            img = tk.PhotoImage(file=icon_file)
            root.iconphoto(True, img)
            return
    except Exception:
        pass

    # Fall back to the embedded base64 image
    try:
        data = base64.b64decode(_ICON_B64)
        img  = tk.PhotoImage(data=data)
        root.iconphoto(True, img)
    except Exception:
        pass   # silently skip on Wayland or other environments where this fails


# ---------------------------------------------------------------------------
# Widget log handler
# ---------------------------------------------------------------------------

class _WidgetLogHandler(logging.Handler):
    """
    Logging handler that appends formatted records to a ScrolledText widget.
    Each severity level is coloured differently via Tk text tags.
    Thread-safe: all widget writes are posted to the main thread via after().
    """

    LEVEL_COLORS = {
        "DEBUG":    "#6b7280",
        "INFO":     "#d4d4d4",
        "WARNING":  "#facc15",
        "ERROR":    "#f87171",
        "CRITICAL": "#f87171",
    }

    def __init__(self, widget: scrolledtext.ScrolledText) -> None:
        super().__init__()
        self._widget = widget
        self.setFormatter(logging.Formatter("%(levelname)-8s %(name)s — %(message)s"))
        # Register a colour tag for every severity level up-front
        for level, color in self.LEVEL_COLORS.items():
            widget.tag_configure(level, foreground=color)

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record) + "\n"
        # Widget is not thread-safe — schedule the write on the main thread
        self._widget.after(0, self._append, msg, record.levelname)

    def _append(self, msg: str, level: str) -> None:
        # Must be called on the main thread
        self._widget.configure(state="normal")
        self._widget.insert(tk.END, msg, level)
        self._widget.see(tk.END)
        self._widget.configure(state="disabled")


# ---------------------------------------------------------------------------
# Tooltip helper
# ---------------------------------------------------------------------------

class _Tooltip:
    """
    Show a small floating label near a widget after a short hover delay.

    Usage:
        _Tooltip(some_widget, "Explanation text shown on hover.")
    """

    def __init__(self, widget: tk.Widget, text: str, delay: int = 600) -> None:
        self._widget   = widget
        self._text     = text
        self._delay    = delay
        self._after_id: Optional[str] = None
        self._tw:       Optional[tk.Toplevel] = None
        # Use add="+" so existing bindings on the widget are not overwritten
        widget.bind("<Enter>",       self._schedule, add="+")
        widget.bind("<Leave>",       self._cancel,   add="+")
        widget.bind("<ButtonPress>", self._cancel,   add="+")

    def _schedule(self, _event) -> None:
        # Cancel any pending show, then schedule a new one after the delay
        self._cancel(None)
        self._after_id = self._widget.after(self._delay, self._show)

    def _cancel(self, _event) -> None:
        # Abort a pending show and destroy any visible tip window
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tw:
            self._tw.destroy()
            self._tw = None

    def _show(self) -> None:
        # Position the tip just below the widget's bottom-left corner
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tw = tk.Toplevel(self._widget)
        self._tw.wm_overrideredirect(True)
        self._tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._tw,
            text=self._text,
            justify=tk.LEFT,
            background="#fffde7",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 9) if sys.platform == "win32" else ("Helvetica", 9),
            wraplength=320,
            padx=6,
            pady=4,
        ).pack()


# ---------------------------------------------------------------------------
# Scrollable tab frame
# ---------------------------------------------------------------------------

class _ScrollableFrame(ttk.Frame):
    """
    A ttk.Frame whose content area scrolls vertically.

    SCROLL BINDING STRATEGY
    -----------------------
    The classic approach is bind_all on <MouseWheel> on Enter, and
    unbind_all on Leave.  The risk: if the cursor moves very quickly from
    one scrollable frame to another, the Leave event of the first may fire
    after the Enter event of the second, leaving the binding pointed at the
    wrong handler.

    Fix: a class-level ``_focused`` reference tracks which instance
    currently owns the wheel binding.  The guard in _unbind_wheel checks
    that ``self`` is still the focused frame before removing the binding,
    so a late-firing Leave on an already-superseded frame is a no-op.

    Usage:
        sf = _ScrollableFrame(notebook)
        notebook.add(sf, text="Tab Name")
        # Add widgets to sf.inner — NOT to sf directly.
        ttk.Label(sf.inner, text="Hello").pack()
    """

    # Tracks whichever instance currently holds global wheel focus
    _focused: Optional[_ScrollableFrame] = None

    def __init__(self, parent, padding: int = 10, **kw) -> None:
        super().__init__(parent, **kw)

        self._canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self._sb     = ttk.Scrollbar(self, orient="vertical",
                                     command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._sb.set)

        self._sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.inner = ttk.Frame(self._canvas, padding=padding)
        self._win  = self._canvas.create_window((0, 0), window=self.inner,
                                                anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # Activate scrolling while the cursor is inside this canvas
        self._canvas.bind("<Enter>", self._bind_wheel)
        self._canvas.bind("<Leave>", self._unbind_wheel)

    def _on_inner_configure(self, _event) -> None:
        # Keep the scroll region in sync with the inner frame's actual height
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        # Stretch the inner frame to fill the canvas width
        self._canvas.itemconfigure(self._win, width=event.width)

    def _bind_wheel(self, _event) -> None:
        # Claim wheel focus and install the global binding
        _ScrollableFrame._focused = self
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)
        self._canvas.bind_all("<Button-4>",   self._on_wheel)
        self._canvas.bind_all("<Button-5>",   self._on_wheel)

    def _unbind_wheel(self, _event) -> None:
        # Only release the binding if we are still the focused frame.
        # A late-firing Leave on a superseded frame would otherwise unbind
        # the handler that the newly-focused frame just installed.
        if _ScrollableFrame._focused is self:
            _ScrollableFrame._focused = None
            self._canvas.unbind_all("<MouseWheel>")
            self._canvas.unbind_all("<Button-4>")
            self._canvas.unbind_all("<Button-5>")

    def _on_wheel(self, event) -> None:
        # Handle Linux Button-4/5 and Windows/macOS delta-based events
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(int(-event.delta / 120), "units")


# ---------------------------------------------------------------------------
# Style constants and theme
# ---------------------------------------------------------------------------

_ACCENT     = "#4f46e5"   # indigo-600 — primary interactive colour
_ACCENT2    = "#6366f1"   # indigo-500 — hover state
_BG_DARK    = "#1e1e2e"   # log panel background
_MUTED      = "#9ca3af"   # de-emphasised text
_SMALL_FONT = ("Segoe UI", 8)  if sys.platform == "win32" else ("Helvetica", 8)
_BODY_FONT  = ("Segoe UI", 10) if sys.platform == "win32" else ("Helvetica", 10)
_BOLD_FONT  = ("Segoe UI", 10, "bold") if sys.platform == "win32" else ("Helvetica", 10, "bold")


def _apply_theme(root: tk.Tk) -> None:
    """Apply a clean modern palette built on top of the clam base theme."""
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".",
        background  = "#f8f9fb",
        foreground  = "#1e1b4b",
        font        = _BODY_FONT,
        relief      = "flat",
    )
    style.configure("TNotebook",  background="#e8eaf0", tabmargins=[2, 4, 0, 0])
    style.configure("TNotebook.Tab",
        padding    = [14, 6],
        font       = _BOLD_FONT,
        foreground = "#4b5563",
        background = "#dde1ea",
    )
    style.map("TNotebook.Tab",
        background = [("selected", "#f8f9fb"), ("active", "#eef0f6")],
        foreground = [("selected", _ACCENT),   ("active", "#1e1b4b")],
        expand     = [("selected", [1, 1, 1, 0])],
    )
    style.configure("TLabelframe",
        background  = "#f8f9fb",
        bordercolor = "#d1d5db",
        relief      = "groove",
    )
    style.configure("TLabelframe.Label",
        foreground = _ACCENT,
        font       = ("Segoe UI", 9, "bold") if sys.platform == "win32"
                     else ("Helvetica", 9, "bold"),
    )
    style.configure("TButton",
        padding     = [10, 5],
        background  = _ACCENT,
        foreground  = "#ffffff",
        borderwidth = 0,
        relief      = "flat",
    )
    style.map("TButton",
        background = [("active", _ACCENT2), ("pressed", "#4338ca"),
                      ("disabled", "#a5b4fc")],
    )
    style.configure("Secondary.TButton", background="#e0e7ff", foreground=_ACCENT)
    style.map("Secondary.TButton", background=[("active", "#c7d2fe")])

    # Larger primary-action button used for "START AUTOMATION"
    style.configure("Primary.TButton",
        padding     = [20, 10],
        background  = _ACCENT,
        foreground  = "#ffffff",
        font        = _BOLD_FONT,
        borderwidth = 0,
        relief      = "flat",
    )
    style.map("Primary.TButton",
        background = [("active", _ACCENT2), ("pressed", "#4338ca"),
                      ("disabled", "#a5b4fc")],
    )
    style.configure("TEntry",
        fieldbackground = "#ffffff",
        bordercolor     = "#d1d5db",
        lightcolor      = "#d1d5db",
        darkcolor       = "#d1d5db",
    )
    style.configure("TCheckbutton", background="#f8f9fb")
    style.configure("TRadiobutton", background="#f8f9fb")
    style.configure("TFrame",       background="#f8f9fb")
    style.configure("TSeparator",   background="#e5e7eb")
    style.configure("TSpinbox", fieldbackground="#ffffff", bordercolor="#d1d5db")
    style.configure("Heading.TLabel", font=_BOLD_FONT, foreground=_ACCENT)
    style.configure("Accent.TLabel",  foreground=_ACCENT)
    style.configure("Muted.TLabel",   foreground=_MUTED)
    style.configure("Danger.TButton", background="#ef4444", foreground="#ffffff",
                    borderwidth=0)
    style.map("Danger.TButton", background=[("active", "#dc2626")])


# ---------------------------------------------------------------------------
# Main application class
# ---------------------------------------------------------------------------

class RenSightGUI:
    """
    Root application window for Ren'Sight.

    Manages six notebook tabs.  All heavy work runs in daemon threads;
    UI updates are posted back to the main thread via root.after().
    User preferences for the Auto Pilot are loaded from rensight_config.json
    at startup and saved on demand from the Settings tab.
    """

    APP_NAME    = "Ren'Sight"
    APP_VERSION = "v0.2.2-alpha"
    WINDOW_SIZE = "980x840"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"{self.APP_NAME}  {self.APP_VERSION}")
        root.geometry(self.WINDOW_SIZE)
        root.minsize(800, 600)
        root.resizable(True, True)
        _apply_theme(root)
        _set_icon(root)

        # Load persisted settings, falling back to defaults for missing keys
        self._config: Dict[str, Any] = _load_config()

        # Reference to the most-recently built graph (used by "Show Stats")
        self._last_graph = None

        self._build_ui()
        self._setup_logging()
        self._setup_keyboard_shortcuts()

        # Show the alpha disclaimer after the window has fully rendered
        self.root.after(300, self._show_alpha_disclaimer)

    # ── Alpha disclaimer ──────────────────────────────────────────────────────

    def _show_alpha_disclaimer(self) -> None:
        # Warn users that this is an unsupported early release
        messagebox.showinfo(
            f"Welcome to {self.APP_NAME} {self.APP_VERSION}",
            f"{self.APP_NAME}  {self.APP_VERSION}\n\n"
            "⚠  This is an early alpha release.\n"
            "Please back up your Ren'Py script files before use.\n\n"
            "Features may be incomplete or change without notice.\n"
            "Report issues and feedback via the project repository.",
        )

    # ── UI skeleton ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Root container with a small gutter on all sides
        root_frame = ttk.Frame(self.root, padding=(8, 6, 8, 0))
        root_frame.pack(fill=tk.BOTH, expand=True)

        # Header bar
        hdr = ttk.Frame(root_frame)
        hdr.pack(fill=tk.X, pady=(0, 6))
        title_frame = ttk.Frame(hdr)
        title_frame.pack(side=tk.LEFT)
        ttk.Label(
            title_frame,
            text=self.APP_NAME,
            font=("Segoe UI", 15, "bold") if sys.platform == "win32"
                 else ("Helvetica", 15, "bold"),
            foreground=_ACCENT,
        ).pack(anchor="w")
        ttk.Label(
            title_frame,
            text=f"Narrative analysis toolkit for Ren'Py visual novels  ·  {self.APP_VERSION}",
            font=_SMALL_FONT,
            foreground=_MUTED,
        ).pack(anchor="w")

        # self.supportbutton

        # Notebook
        self._nb = ttk.Notebook(root_frame)
        self._nb.pack(fill=tk.BOTH, expand=True)

        self._build_tab_autopilot()   # Tab 0
        self._build_tab_parse()       # Tab 1
        self._build_tab_graph()       # Tab 2
        self._build_tab_survey()      # Tab 3
        self._build_tab_analyser()    # Tab 4
        self._build_tab_settings()    # Tab 5

        # Status bar — between notebook and log panel
        status_frame = ttk.Frame(root_frame)
        status_frame.pack(fill=tk.X, pady=(4, 0))
        self._status_label = ttk.Label(
            status_frame, text="●  Ready", foreground="#6b7280", font=_SMALL_FONT,
        )
        self._status_label.pack(side=tk.LEFT, padx=4)
        self._progress = ttk.Progressbar(
            status_frame, mode="indeterminate", length=160,
        )
        self._progress.pack(side=tk.RIGHT, padx=4)
        self._progress.pack_forget()   # hidden until a task is active

        # Log panel
        ttk.Separator(root_frame, orient="horizontal").pack(fill=tk.X, pady=(4, 0))
        log_hdr = ttk.Frame(root_frame)
        log_hdr.pack(fill=tk.X)
        ttk.Label(
            log_hdr, text="Log",
            font=("Segoe UI", 9, "bold") if sys.platform == "win32"
                 else ("Helvetica", 9, "bold"),
            foreground="#6b7280",
        ).pack(side=tk.LEFT, padx=4, pady=2)
        ttk.Button(
            log_hdr, text="Clear", style="Secondary.TButton",
            command=self._clear_log,
        ).pack(side=tk.RIGHT, pady=2, padx=4)
        self._log_box = scrolledtext.ScrolledText(
            root_frame, height=6, state="disabled",
            font=("Courier New", 9) if sys.platform == "win32" else ("Courier", 9),
            background=_BG_DARK, foreground="#d4d4d4",
            insertbackground="#d4d4d4", wrap=tk.WORD,
        )
        self._log_box.pack(fill=tk.BOTH, expand=False, pady=(0, 4))

    # ── Support Links & Buttons ───────────────────────────────────────────────────

    # def supportbutton():

    #     patreon_icon_path = os.path.join(_GUI_DIR, "patreon_icon.png")
    #     patreon_icon = tk.PhotoImage(file="icons/patreon.png")

    #     support_btn = ttk.Button(
    #         parent_frame,
    #         text=" Support Me",
    #         image=patreon_icon,
    #         compound="left",
    #         command=lambda: webbrowser.open_new_tab("https://www.patreon.com/YOUR_PAGE")
    #     ).pack()

    # ── Tab 0 — Auto Pilot ───────────────────────────────────────────────────

    def _build_tab_autopilot(self) -> None:
        sf  = _ScrollableFrame(self._nb)
        tab = sf.inner
        self._nb.add(sf, text="  Auto Pilot  ")

        # Intro blurb
        intro = ttk.Frame(tab)
        intro.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        ttk.Label(
            intro,
            text="⚡  One-click automation — parse, graph, and survey in a single step.",
            style="Heading.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            intro,
            text=(
                "Point Ren'Sight at your game root and press Start.  "
                "Change defaults in the Settings tab.  "
                "Fine-tune individual steps in the advanced tabs."
            ),
            foreground=_MUTED,
        ).pack(anchor="w")

        # Project root
        project_frame = ttk.LabelFrame(tab, text=" Project ", padding=10)
        project_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        self._dash_game_root = self._create_path_row(
            project_frame, "Game root directory:", "dir", row=0,
        )
        ttk.Label(
            project_frame,
            text=(
                "Output is saved to a folder whose name is configured in Settings "
                "(default: rensight_output/), placed next to the game root."
            ),
            foreground=_MUTED, font=_SMALL_FONT,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        project_frame.columnconfigure(1, weight=1)

        # Step toggles
        steps_frame = ttk.LabelFrame(tab, text=" Steps ", padding=12)
        steps_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        # Step 1: Parse — always active
        ttk.Label(
            steps_frame, text="①  Parse game scripts", foreground=_ACCENT,
        ).grid(row=0, column=0, sticky="w", pady=3)
        ttk.Label(
            steps_frame, text="Always runs  ·  produces parsed_script.json",
            foreground=_MUTED, font=_SMALL_FONT,
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))

        # Step 2: Graph — optional toggle
        self._dash_do_graph = tk.BooleanVar(value=True)
        _cb_graph = ttk.Checkbutton(
            steps_frame, text="②  Build narrative graph",
            variable=self._dash_do_graph,
        )
        _cb_graph.grid(row=1, column=0, sticky="w", pady=3)
        _Tooltip(_cb_graph,
                 "Exports graph formats configured in Settings → Narrative Graph Exports.\n"
                 "Default: JSON + Interactive HTML.")
        ttk.Label(
            steps_frame, text="Uses export formats configured in Settings",
            foreground=_MUTED, font=_SMALL_FONT,
        ).grid(row=1, column=1, sticky="w", padx=(12, 0))

        # Step 3: Survey — optional toggle
        self._dash_do_survey = tk.BooleanVar(value=True)
        _cb_survey = ttk.Checkbutton(
            steps_frame, text="③  Generate player survey",
            variable=self._dash_do_survey,
        )
        _cb_survey.grid(row=2, column=0, sticky="w", pady=3)
        _Tooltip(_cb_survey,
                 "Generates surveys in formats selected in Settings → Survey Formats.\n"
                 "Default: HTML only.")
        ttk.Label(
            steps_frame, text="Uses question sets and formats configured in Settings",
            foreground=_MUTED, font=_SMALL_FONT,
        ).grid(row=2, column=1, sticky="w", padx=(12, 0))

        # Step 4: Analyse — locked
        ttk.Checkbutton(
            steps_frame, text="④  Analyse feedback", state="disabled",
        ).grid(row=3, column=0, sticky="w", pady=3)
        ttk.Label(
            steps_frame, text="🔒  Coming in v0.3",
            foreground=_MUTED, font=_SMALL_FONT,
        ).grid(row=3, column=1, sticky="w", padx=(12, 0))

        steps_frame.columnconfigure(1, weight=1)

        # Primary action button
        self._dash_start_btn = ttk.Button(
            tab,
            text="▶   START AUTOMATION",
            style="Primary.TButton",
            command=self._run_auto_process,
        )
        self._dash_start_btn.grid(
            row=3, column=0, columnspan=3,
            pady=(14, 4), ipadx=16, ipady=4,
        )
        ttk.Label(
            tab,
            text="Keyboard shortcut: Ctrl+R  (active on all tabs)",
            foreground=_MUTED, font=_SMALL_FONT, justify=tk.CENTER,
        ).grid(row=4, column=0, columnspan=3, pady=(0, 8))

        tab.columnconfigure(1, weight=1)

    # ── Tab 1 — Game Parser ─────────────────────────────────────────────────

    def _build_tab_parse(self) -> None:
        sf  = _ScrollableFrame(self._nb)
        tab = sf.inner
        self._nb.add(sf, text="  Game Parser  ")

        self._parse_game_dir   = self._create_path_row(
            tab, "Game / script directory:", "dir", row=0,
        )
        self._parse_output_dir = self._create_path_row(
            tab, "Output directory:", "dir", row=1,
        )

        opts = ttk.LabelFrame(tab, text=" Options ", padding=10)
        opts.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 4))

        ttk.Label(opts, text="Game version:").grid(row=0, column=0, sticky="w")
        self._parse_version = ttk.Entry(opts, width=16)
        self._parse_version.insert(0, "unknown")
        self._parse_version.grid(row=0, column=1, sticky="w", padx=(6, 24))

        ttk.Label(opts, text="Context lines:").grid(row=0, column=2, sticky="w")
        self._parse_ctx_lines = tk.StringVar(value="4")
        _sp = ttk.Spinbox(opts, from_=1, to=10,
                          textvariable=self._parse_ctx_lines, width=5)
        _sp.grid(row=0, column=3, sticky="w", padx=6)
        _Tooltip(_sp,
                 "Number of dialogue lines captured before each menu as context.\n"
                 "Higher values give richer context but produce larger JSON files.")

        ttk.Button(
            tab, text="⚙  Parse Game Scripts  (Ctrl+R)",
            command=self._run_parse,
        ).grid(row=3, column=0, columnspan=3, pady=(14, 4))

        tab.columnconfigure(1, weight=1)

    # ── Tab 2 — Narrative Graph ───────────────────────────────────────────────

    def _build_tab_graph(self) -> None:
        sf  = _ScrollableFrame(self._nb)
        tab = sf.inner
        self._nb.add(sf, text="  Narrative Graph  ")

        src_frame = ttk.LabelFrame(tab, text=" Input ", padding=10)
        src_frame.pack(fill=tk.X, pady=(0, 8))
        self._graph_json_path  = self._create_path_row(
            src_frame, "Parsed script JSON:", "file",
            filetypes=[("JSON", "*.json")], row=0,
        )
        self._graph_output_dir = self._create_path_row(
            src_frame, "Output directory:", "dir", row=1,
        )
        src_frame.columnconfigure(1, weight=1)

        fmt_frame = ttk.LabelFrame(tab, text=" Export Formats ", padding=10)
        fmt_frame.pack(fill=tk.X, pady=(0, 8))

        self._graph_export_json = tk.BooleanVar(value=True)
        self._graph_export_dot  = tk.BooleanVar(value=False)
        self._graph_export_png  = tk.BooleanVar(value=False)
        self._graph_export_svg  = tk.BooleanVar(value=False)
        self._graph_export_html = tk.BooleanVar(value=False)

        for i, (var, label, note, tip) in enumerate([
            (self._graph_export_json, "JSON",
             "",
             "Machine-readable graph: nodes, edges, and label metadata."),
            (self._graph_export_dot,  "DOT",
             "",
             "Plain-text DOT file; render manually with the Graphviz CLI."),
            (self._graph_export_png,  "PNG image",
             "",
             "Rasterised graph image.  The 'dot' Graphviz binary must be on PATH."),
            (self._graph_export_svg,  "SVG image",
             "",
             "Scalable vector image.  The 'dot' Graphviz binary must be on PATH."),
            (self._graph_export_html, "Interactive HTML",
             "",
             "Browser-based interactive graph via vis.js — no extra tools required."),
        ]):
            cb = ttk.Checkbutton(fmt_frame, text=f"{label}  {note}", variable=var)
            cb.grid(row=i // 2, column=i % 2 * 2, sticky="w", padx=(0, 24), pady=2)
            _Tooltip(cb, tip)

        stats_frame = ttk.LabelFrame(tab, text=" Graph Statistics ", padding=8)
        stats_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self._graph_stats_box = scrolledtext.ScrolledText(
            stats_frame, height=10, state="disabled",
            font=("Courier New", 9) if sys.platform == "win32" else ("Courier", 9),
            wrap=tk.WORD, background="#f4f4f8",
        )
        self._graph_stats_box.pack(fill=tk.BOTH, expand=True)

        btn_row = ttk.Frame(tab)
        btn_row.pack(pady=6)
        ttk.Button(
            btn_row, text="⚙  Build Graph  (Ctrl+R)",
            command=self._run_build_graph,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btn_row, text="📊  Show Stats",
            style="Secondary.TButton",
            command=self._show_graph_stats,
        ).pack(side=tk.LEFT, padx=4)

    # ── Tab 3 — Survey Generator ──────────────────────────────────────────────

    def _build_tab_survey(self) -> None:
        sf  = _ScrollableFrame(self._nb)
        tab = sf.inner
        self._nb.add(sf, text="  Survey Generator  ")

        # Paths
        path_frame = ttk.LabelFrame(tab, text=" Input / Output ", padding=10)
        path_frame.pack(fill=tk.X, pady=(0, 8))
        self._survey_json_path  = self._create_path_row(
            path_frame, "Parsed script / JSON:", "file",
            filetypes=[("JSON", "*.json")], row=0,
        )
        self._survey_output_dir = self._create_path_row(
            path_frame, "Output directory:", "dir", row=1,
        )
        _game_dir_label = self._create_path_row(
            path_frame, "Game dir (narrative flow only):", "dir", row=2,
        )
        self._survey_game_dir = _game_dir_label
        _Tooltip(_game_dir_label,
                 "Only required when Menu Ordering is set to 'Narrative flow (BFS)'.\n"
                 "Leave blank for all other ordering modes.")

        # Custom output filename
        ttk.Label(
            path_frame, text="Output filename (no extension):",
        ).grid(row=3, column=0, sticky="w", padx=(0, 8), pady=(6, 3))
        _fname_inner = ttk.Frame(path_frame)
        _fname_inner.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(6, 3))
        self._survey_base_name = ttk.Entry(_fname_inner, width=28)
        self._survey_base_name.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            _fname_inner,
            text="Leave blank to use defaults  (feedback_template.txt / survey.html / …)",
            foreground=_MUTED, font=_SMALL_FONT,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        _fname_inner.columnconfigure(0, weight=0)
        _fname_inner.columnconfigure(1, weight=1)
        path_frame.columnconfigure(1, weight=1)

        # Survey intro text
        intro_frame = ttk.LabelFrame(tab, text=" Survey Introduction Text ", padding=10)
        intro_frame.pack(fill=tk.X, pady=(0, 8))
        from exporters.survey.survey_builder import DEFAULT_INTRO_TEXT   # type: ignore[import]
        self._survey_intro = tk.Text(
            intro_frame, height=4, wrap=tk.WORD, font=_BODY_FONT,
            relief="solid", borderwidth=1,
        )
        self._survey_intro.insert("1.0", DEFAULT_INTRO_TEXT)
        self._survey_intro.pack(fill=tk.X)
        ttk.Button(
            intro_frame, text="Reset to default", style="Secondary.TButton",
            command=lambda: (
                self._survey_intro.delete("1.0", tk.END),
                self._survey_intro.insert("1.0", DEFAULT_INTRO_TEXT),
            ),
        ).pack(anchor="e", pady=(4, 0))

        # Two-column section
        cols = ttk.Frame(tab)
        cols.pack(fill=tk.X, pady=(0, 8))
        left  = ttk.Frame(cols)
        right = ttk.Frame(cols)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Output formats
        fmt_frame = ttk.LabelFrame(left, text=" Output Formats ", padding=8)
        fmt_frame.pack(fill=tk.X, pady=(0, 6))
        self._fmt_vars: Dict[str, tk.BooleanVar] = {}
        fmt_defaults = {"txt": True, "html": True, "markdown": False,
                        "csv": False, "json": False}
        for col, fmt in enumerate(["txt", "markdown", "csv", "json", "html"]):
            var = tk.BooleanVar(value=fmt_defaults.get(fmt, False))
            self._fmt_vars[fmt] = var
            ttk.Checkbutton(
                fmt_frame, text=fmt.upper(), variable=var,
            ).grid(row=0, column=col, padx=6, pady=2)

        # Menu ordering
        ord_frame = ttk.LabelFrame(left, text=" Menu Ordering ", padding=8)
        ord_frame.pack(fill=tk.X, pady=(0, 6))
        self._menu_order = tk.StringVar(value="as_extracted")
        for i, (val, lbl, tip) in enumerate([
            ("as_extracted",   "As extracted",
             "Output menus in the order the parser found them."),
            ("file_line",      "File / line",
             "Sort by source file, then by line number within each file."),
            ("label_alpha",    "Label A→Z",
             "Sort menus alphabetically by the label they belong to."),
            ("choice_id",      "Choice ID",
             "Sort by the generated choice ID (label_name + counter)."),
            ("narrative_flow", "Narrative flow (BFS) ★",
             "Order menus by BFS traversal from 'start'.  Game Dir must be set."),
        ]):
            rb = ttk.Radiobutton(ord_frame, text=lbl,
                                 variable=self._menu_order, value=val)
            rb.grid(row=i // 2, column=i % 2, sticky="w", padx=4, pady=1)
            _Tooltip(rb, tip)

        # Misc options
        misc_frame = ttk.LabelFrame(left, text=" Options ", padding=8)
        misc_frame.pack(fill=tk.X, pady=(0, 6))
        self._include_context   = tk.BooleanVar(value=True)
        self._randomise_choices = tk.BooleanVar(value=False)
        self._remove_duplicates = tk.BooleanVar(value=True)
        for row, (var, lbl, tip) in enumerate([
            (self._include_context,
             "Include dialogue context",
             "Prepend captured dialogue lines before each menu block in the survey."),
            (self._randomise_choices,
             "Randomise choice order",
             "Shuffle choices within each menu to reduce selection-order bias."),
            (self._remove_duplicates,
             "Remove duplicate menus",
             "Skip any menu whose choice text is identical to a previously seen menu."),
        ]):
            cb = ttk.Checkbutton(misc_frame, text=lbl, variable=var)
            cb.grid(row=row, column=0, sticky="w", pady=1)
            _Tooltip(cb, tip)

        # Question sets
        qs_frame = ttk.LabelFrame(right, text=" Question Sets ", padding=8)
        qs_frame.pack(fill=tk.BOTH, expand=True)
        defaults_qs = {"clarity", "preference", "narrative_impact"}
        self._qs_vars: Dict[str, tk.BooleanVar] = {}
        for i, qs in enumerate(_ALL_QUESTION_SETS):
            var = tk.BooleanVar(value=(qs in defaults_qs))
            self._qs_vars[qs] = var
            ttk.Checkbutton(
                qs_frame, text=qs.replace("_", " ").title(), variable=var,
            ).grid(row=i, column=0, sticky="w", pady=1)
        qs_btn_row = ttk.Frame(qs_frame)
        qs_btn_row.grid(row=len(_ALL_QUESTION_SETS), column=0, pady=(6, 0), sticky="w")
        ttk.Button(
            qs_btn_row, text="Select all", style="Secondary.TButton",
            command=lambda: [v.set(True) for v in self._qs_vars.values()],
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            qs_btn_row, text="Deselect all", style="Secondary.TButton",
            command=lambda: [v.set(False) for v in self._qs_vars.values()],
        ).pack(side=tk.LEFT)

        # HTML section grouping
        grp_frame = ttk.LabelFrame(tab, text=" HTML Section Grouping ", padding=10)
        grp_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(
            grp_frame,
            text=(
                "Controls how choice menus are grouped in the HTML survey.\n"
                "Has no effect on TXT / Markdown / CSV output."
            ),
            foreground="#6b7280", wraplength=680,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self._html_group_mode = tk.StringVar(value="narrative_block")
        _GROUP_OPTS = [
            ("narrative_block",
             "Narrative block  (recommended)",
             "Merges companion files into one group per day/chapter.\n"
             "e.g. day0.rpy + day0events.rpy → one 'Day 0' group."),
            ("client_toggle",
             "Dual view  (toggle button in HTML)",
             "Adds a button so readers can switch between Narrative block\n"
             "and Source file views on the fly — no page reload needed."),
            ("config",
             "Custom config  (developer-supplied JSON)",
             "You define exactly which files belong to which group.\n"
             "Most flexible; useful for non-linear or heavily modular projects."),
            ("label_only",
             "Descriptive labels",
             "Keeps one group per file, but uses clearer labels.\n"
             "e.g. 'Day 0 — Events' instead of 'Day 0 Events'."),
            ("file",
             "Source file  (original behaviour)",
             "One collapsible group per .rpy file, labelled by filename.\n"
             "Best if files already map 1-to-1 to narrative sections."),
        ]
        for row_i, (val, title, desc) in enumerate(_GROUP_OPTS):
            rb = ttk.Radiobutton(
                grp_frame, text=title,
                variable=self._html_group_mode, value=val,
                command=self._on_group_mode_change,
            )
            rb.grid(row=1 + row_i * 2, column=0, sticky="nw", padx=(2, 16), pady=(4, 0))
            _Tooltip(rb, desc)
            ttk.Label(
                grp_frame, text=desc, foreground=_MUTED,
                font=_SMALL_FONT, justify=tk.LEFT,
            ).grid(row=2 + row_i * 2, column=0, sticky="w", padx=(22, 0), pady=(0, 2))

        # Config-file picker — revealed only when mode == "config"
        self._grp_config_frame = ttk.Frame(grp_frame)
        self._grp_config_frame.grid(
            row=1, column=1, rowspan=10, sticky="nw", padx=(8, 0),
        )
        ttk.Label(
            self._grp_config_frame,
            text="Group config JSON:",
            font=(("Segoe UI", 9, "bold") if sys.platform == "win32"
                  else ("Helvetica", 9, "bold")),
        ).pack(anchor="w")
        ttk.Label(
            self._grp_config_frame,
            text='Format: {"groups": [{"name": "Day 0",\n         "files": ["game/scripts/day0.rpy", ...]}, ...]}',
            foreground=_MUTED,
            font=(("Courier New", 7) if sys.platform == "win32" else ("Courier", 8)),
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(2, 4))
        _cfg_row = ttk.Frame(self._grp_config_frame)
        _cfg_row.pack(fill=tk.X)
        self._grp_config_path = ttk.Entry(_cfg_row, width=34)
        self._grp_config_path.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # FIX: cancel-safe browse (previous lambda wiped the entry on Cancel)
        ttk.Button(
            _cfg_row, text="Browse…", style="Secondary.TButton",
            command=lambda: self._safe_browse(
                self._grp_config_path, "file",
                filetypes=[("JSON", "*.json"), ("All", "*")],
            ),
        ).pack(side=tk.LEFT, padx=(4, 0))
        grp_frame.columnconfigure(1, weight=1)

        # FIX: sync config-frame visibility with the initial StringVar value.
        # Without this call, the frame would remain hidden if the default were
        # ever changed to "config" in a future version.
        self._on_group_mode_change()

        ttk.Button(
            tab, text="⚙  Generate Surveys  (Ctrl+R)",
            command=self._run_survey,
        ).pack(pady=(4, 0))

    # ── Grouping mode callback ────────────────────────────────────────────────

    def _on_group_mode_change(self) -> None:
        # Show or hide the developer config picker based on the selected mode
        if self._html_group_mode.get() == "config":
            self._grp_config_frame.grid()
        else:
            self._grp_config_frame.grid_remove()

    # ── Tab 4 — Feedback Analyser (stub) ──────────────────────────────────────

    def _build_tab_analyser(self) -> None:
        sf  = _ScrollableFrame(self._nb)
        tab = sf.inner
        self._nb.add(sf, text="  Feedback Analyser  ")
        ttk.Label(
            tab,
            text="Feedback Analyser — coming in v0.3",
            foreground=_MUTED,
            font=("Segoe UI", 12, "italic") if sys.platform == "win32"
                 else ("Helvetica", 12, "italic"),
        ).pack(pady=40)

    # ── Tab 5 — Settings ─────────────────────────────────────────────────────

    def _build_tab_settings(self) -> None:
        sf  = _ScrollableFrame(self._nb)
        tab = sf.inner
        self._nb.add(sf, text="  Settings ⚙  ")

        ttk.Label(
            tab,
            text=(
                "These defaults are used by the Auto Pilot.  "
                "Changes take effect after you click Save Settings."
            ),
            foreground=_MUTED, font=_SMALL_FONT,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        # ── Parser section ──
        parser_frame = ttk.LabelFrame(tab, text=" Parser ", padding=10)
        parser_frame.grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=(0, 6), pady=(0, 8),
        )
        ttk.Label(parser_frame, text="Game version:").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        self._cfg_game_version = ttk.Entry(parser_frame, width=18)
        self._cfg_game_version.insert(0, str(self._config["auto_game_version"]))
        self._cfg_game_version.grid(row=0, column=1, sticky="w", padx=(0, 24))

        ttk.Label(parser_frame, text="Context lines:").grid(
            row=0, column=2, sticky="w", padx=(0, 6))
        self._cfg_ctx_lines = tk.StringVar(
            value=str(self._config["auto_context_lines"]))
        _sp = ttk.Spinbox(parser_frame, from_=1, to=10,
                          textvariable=self._cfg_ctx_lines, width=5)
        _sp.grid(row=0, column=3, sticky="w")
        _Tooltip(_sp, "Number of dialogue lines captured before each menu as context.")

        ttk.Label(parser_frame, text="Output folder name:").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        self._cfg_output_folder = ttk.Entry(parser_frame, width=26)
        self._cfg_output_folder.insert(0, str(self._config["auto_output_folder"]))
        self._cfg_output_folder.grid(
            row=1, column=1, columnspan=3, sticky="w", pady=(6, 0))
        _Tooltip(self._cfg_output_folder,
                 "Name of the output directory created next to the game root.\n"
                 "e.g. 'rensight_output'  →  GameRoot/../rensight_output/")

        # ── Graph exports section ──
        graph_frame = ttk.LabelFrame(tab, text=" Narrative Graph Exports ", padding=10)
        graph_frame.grid(
            row=1, column=2, columnspan=2, sticky="ew", padx=(6, 0), pady=(0, 8),
        )
        self._cfg_graph_vars: Dict[str, tk.BooleanVar] = {}
        for i, (key, label, tip) in enumerate([
            ("auto_graph_json", "JSON",             "Machine-readable graph file."),
            ("auto_graph_dot",  "DOT",              "Graphviz DOT source."),
            ("auto_graph_png",  "PNG image",        "Requires Graphviz on PATH."),
            ("auto_graph_svg",  "SVG image",        "Requires Graphviz on PATH."),
            ("auto_graph_html", "Interactive HTML", "Browser-based graph via vis.js."),
        ]):
            var = tk.BooleanVar(value=bool(self._config[key]))
            self._cfg_graph_vars[key] = var
            cb = ttk.Checkbutton(graph_frame, text=label, variable=var)
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 16), pady=2)
            _Tooltip(cb, tip)

        # ── Survey section ──
        survey_outer = ttk.LabelFrame(tab, text=" Survey Generator ", padding=10)
        survey_outer.grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=(0, 8),
        )
        s_left = ttk.Frame(survey_outer)
        s_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # Output formats
        fmt_lf = ttk.LabelFrame(s_left, text=" Output Formats ", padding=8)
        fmt_lf.pack(fill=tk.X, pady=(0, 6))
        self._cfg_fmt_vars: Dict[str, tk.BooleanVar] = {}
        for col, (key, label) in enumerate([
            ("auto_fmt_txt",      "TXT"),
            ("auto_fmt_html",     "HTML"),
            ("auto_fmt_markdown", "Markdown"),
            ("auto_fmt_csv",      "CSV"),
            ("auto_fmt_json",     "JSON"),
        ]):
            var = tk.BooleanVar(value=bool(self._config[key]))
            self._cfg_fmt_vars[key] = var
            ttk.Checkbutton(
                fmt_lf, text=label, variable=var,
            ).grid(row=0, column=col, padx=6, pady=2)

        # Menu ordering
        ord_lf = ttk.LabelFrame(s_left, text=" Menu Ordering ", padding=8)
        ord_lf.pack(fill=tk.X, pady=(0, 6))
        self._cfg_menu_order = tk.StringVar(
            value=str(self._config["auto_menu_order"]))
        for i, (val, lbl) in enumerate([
            ("as_extracted",   "As extracted"),
            ("file_line",      "File / line"),
            ("label_alpha",    "Label A→Z"),
            ("choice_id",      "Choice ID"),
            ("narrative_flow", "Narrative flow (BFS) ★"),
        ]):
            ttk.Radiobutton(
                ord_lf, text=lbl, variable=self._cfg_menu_order, value=val,
            ).grid(row=i // 2, column=i % 2, sticky="w", padx=4, pady=1)

        # HTML grouping
        grp_lf = ttk.LabelFrame(s_left, text=" HTML Section Grouping ", padding=8)
        grp_lf.pack(fill=tk.X, pady=(0, 6))
        self._cfg_html_group = tk.StringVar(
            value=str(self._config["auto_html_group"]))
        for i, (val, lbl) in enumerate([
            ("narrative_block", "Narrative block (recommended)"),
            ("client_toggle",   "Dual view"),
            ("config",          "Custom config"),
            ("label_only",      "Descriptive labels"),
            ("file",            "Source file"),
        ]):
            ttk.Radiobutton(
                grp_lf, text=lbl, variable=self._cfg_html_group, value=val,
            ).grid(row=i // 2, column=i % 2, sticky="w", padx=4, pady=1)

        # Misc survey options
        misc_lf = ttk.LabelFrame(s_left, text=" Options ", padding=8)
        misc_lf.pack(fill=tk.X, pady=(0, 6))
        self._cfg_include_context   = tk.BooleanVar(
            value=bool(self._config["auto_include_context"]))
        self._cfg_randomise_choices = tk.BooleanVar(
            value=bool(self._config["auto_randomise_choices"]))
        self._cfg_remove_duplicates = tk.BooleanVar(
            value=bool(self._config["auto_remove_duplicates"]))
        for row, (var, lbl) in enumerate([
            (self._cfg_include_context,   "Include dialogue context"),
            (self._cfg_randomise_choices, "Randomise choice order"),
            (self._cfg_remove_duplicates, "Remove duplicate menus"),
        ]):
            ttk.Checkbutton(
                misc_lf, text=lbl, variable=var,
            ).grid(row=row, column=0, sticky="w", pady=1)

        # Question sets (right column)
        qs_lf = ttk.LabelFrame(survey_outer, text=" Question Sets ", padding=8)
        qs_lf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._cfg_qs_vars: Dict[str, tk.BooleanVar] = {}
        for i, qs in enumerate(_ALL_QUESTION_SETS):
            key = f"auto_qs_{qs}"
            var = tk.BooleanVar(value=bool(self._config.get(key, False)))
            self._cfg_qs_vars[qs] = var
            ttk.Checkbutton(
                qs_lf, text=qs.replace("_", " ").title(), variable=var,
            ).grid(row=i, column=0, sticky="w", pady=1)
        qs_btn_row = ttk.Frame(qs_lf)
        qs_btn_row.grid(row=len(_ALL_QUESTION_SETS), column=0, pady=(6, 0), sticky="w")
        ttk.Button(
            qs_btn_row, text="Select all", style="Secondary.TButton",
            command=lambda: [v.set(True) for v in self._cfg_qs_vars.values()],
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            qs_btn_row, text="Deselect all", style="Secondary.TButton",
            command=lambda: [v.set(False) for v in self._cfg_qs_vars.values()],
        ).pack(side=tk.LEFT)

        # Action buttons
        btn_frame = ttk.Frame(tab)
        btn_frame.grid(row=3, column=0, columnspan=4, pady=(4, 8))
        for w in btn_frame.winfo_children():
            w.destroy()   # clear the broken attempt above

        _rst_btn = ttk.Button(
            btn_frame, text="Reset to Defaults",
            style="Secondary.TButton",
            command=self._reset_settings_to_defaults,
        )
        _rst_btn.pack(side=tk.LEFT, padx=(0, 8))
        _Tooltip(_rst_btn,
                 "Restores all fields to built-in defaults.\n"
                 "Nothing is saved until you click 'Save Settings'.")

        ttk.Button(
            btn_frame, text="💾  Save Settings",
            command=self._save_settings,
        ).pack(side=tk.LEFT)

        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.columnconfigure(2, weight=1)
        tab.columnconfigure(3, weight=1)

    # ── Settings actions ──────────────────────────────────────────────────────

    def _reset_settings_to_defaults(self) -> None:
        # Restore all Settings tk vars to DEFAULT_CONFIG values without saving to disk
        d = DEFAULT_CONFIG

        self._cfg_game_version.delete(0, tk.END)
        self._cfg_game_version.insert(0, str(d["auto_game_version"]))
        self._cfg_ctx_lines.set(str(d["auto_context_lines"]))
        self._cfg_output_folder.delete(0, tk.END)
        self._cfg_output_folder.insert(0, str(d["auto_output_folder"]))

        for key, var in self._cfg_graph_vars.items():
            var.set(bool(d[key]))

        for key, var in self._cfg_fmt_vars.items():
            var.set(bool(d[key]))

        self._cfg_menu_order.set(str(d["auto_menu_order"]))
        self._cfg_html_group.set(str(d["auto_html_group"]))
        self._cfg_include_context.set(bool(d["auto_include_context"]))
        self._cfg_randomise_choices.set(bool(d["auto_randomise_choices"]))
        self._cfg_remove_duplicates.set(bool(d["auto_remove_duplicates"]))

        for qs, var in self._cfg_qs_vars.items():
            var.set(bool(d.get(f"auto_qs_{qs}", False)))

        logger.info("Settings reset to defaults.  Click 'Save Settings' to persist.")

    def _save_settings(self) -> None:
        # Read every Settings tk var into self._config, then write to disk
        try:
            ctx = int(self._cfg_ctx_lines.get())
        except ValueError:
            ctx = 4

        self._config["auto_game_version"]    = self._cfg_game_version.get().strip() or "unknown"
        self._config["auto_context_lines"]   = ctx
        self._config["auto_output_folder"]   = self._cfg_output_folder.get().strip() or "rensight_output"

        for key, var in self._cfg_graph_vars.items():
            self._config[key] = var.get()

        for key, var in self._cfg_fmt_vars.items():
            self._config[key] = var.get()

        self._config["auto_menu_order"]        = self._cfg_menu_order.get()
        self._config["auto_html_group"]        = self._cfg_html_group.get()
        self._config["auto_include_context"]   = self._cfg_include_context.get()
        self._config["auto_randomise_choices"] = self._cfg_randomise_choices.get()
        self._config["auto_remove_duplicates"] = self._cfg_remove_duplicates.get()

        for qs, var in self._cfg_qs_vars.items():
            self._config[f"auto_qs_{qs}"] = var.get()

        _save_config(self._config)
        logger.info("Settings saved to %s", _CONFIG_PATH)
        messagebox.showinfo(
            "Saved",
            "Settings saved.\n"
            "Auto Pilot will use these defaults on the next run.",
        )

    # ── Unified path-row helper ───────────────────────────────────────────────

    def _create_path_row(
        self,
        parent,
        label:       str,
        browse_type: str,
        row:         int,
        filetypes:   Optional[list] = None,
    ) -> ttk.Entry:
        """
        Create a labelled Entry + Browse button row in a grid-layout parent.

        Replaces the former _path_row and _path_row_in helpers, which were
        functionally identical apart from a lambda-formatting difference and
        both shared the same cancel-wipe bug.

        Parameters
        ----------
        parent      : ttk container that uses grid()
        label       : text shown in the Label to the left of the entry
        browse_type : "file" → askopenfilename; anything else → askdirectory
        row         : grid row index for placement
        filetypes   : passed to askopenfilename when browse_type is "file"

        Returns
        -------
        The ttk.Entry widget; callers store the reference to read its value.
        """
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=3,
        )
        entry = ttk.Entry(parent)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(
            parent, text="Browse…", style="Secondary.TButton",
            command=lambda e=entry: self._safe_browse(e, browse_type, filetypes),
        ).grid(row=row, column=2, padx=(6, 0), pady=3)
        return entry

    def _safe_browse(
        self,
        entry:       ttk.Entry,
        browse_type: str,
        filetypes:   Optional[list] = None,
    ) -> None:
        """
        Open a file or directory dialog and update the entry only on confirmation.

        FIX: The previous lambda helpers called entry.delete() before opening
        the dialog.  If the user clicked Cancel the dialog returned an empty
        string, which was then inserted — silently wiping the existing path.
        This method checks for a non-empty result before touching the entry.

        Parameters
        ----------
        entry       : the Entry widget to update on a confirmed selection
        browse_type : "file" → askopenfilename; anything else → askdirectory
        filetypes   : forwarded to askopenfilename (ignored for directories)
        """
        if browse_type == "file":
            selected = filedialog.askopenfilename(
                filetypes=filetypes or [("All", "*")],
            )
        else:
            selected = filedialog.askdirectory()

        # Only update the entry if the user made an actual selection
        if selected:
            entry.delete(0, tk.END)
            entry.insert(0, selected)

    # ── Status bar helpers ────────────────────────────────────────────────────

    def _set_busy(self, message: str) -> None:
        # Show the progress bar and update the status message; call on main thread
        self._status_label.configure(text=f"⏳  {message}", foreground=_ACCENT)
        self._progress.pack(side=tk.RIGHT, padx=4)
        self._progress.start(12)

    def _set_idle(self, message: str = "Ready") -> None:
        # Stop the progress bar and restore idle appearance; call on main thread
        self._progress.stop()
        self._progress.pack_forget()
        self._status_label.configure(text=f"●  {message}", foreground="#6b7280")

    # ── Logging ───────────────────────────────────────────────────────────────

    def _setup_logging(self) -> None:
        # Attach the widget handler to the root logger to capture all modules
        handler = _WidgetLogHandler(self._log_box)
        handler.setLevel(logging.DEBUG)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(handler)

    def _clear_log(self) -> None:
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", tk.END)
        self._log_box.configure(state="disabled")

    # ── Thread helper ─────────────────────────────────────────────────────────

    def _run_in_thread(
        self,
        target,
        *args,
        status: str = "Working…",
        **kwargs,
    ) -> None:
        """
        Spawn target as a daemon thread and manage the status bar automatically.

        The status bar shows 'status' while the thread is running and reverts
        to "Ready" when target returns (or raises).  The finally block posts
        _set_idle via root.after() so it is always safe even if target raises.

        Parameters
        ----------
        target : callable to run in the background thread
        *args  : positional arguments forwarded to target
        status : message shown in the status bar while the thread is active
        **kwargs : keyword arguments forwarded to target
        """
        self.root.after(0, self._set_busy, status)

        def _wrapper() -> None:
            try:
                target(*args, **kwargs)
            finally:
                # Always restore idle state regardless of success or exception
                self.root.after(0, self._set_idle)

        threading.Thread(target=_wrapper, daemon=True).start()

    # ── Keyboard shortcuts ────────────────────────────────────────────────────

    def _setup_keyboard_shortcuts(self) -> None:
        # Map each notebook tab index to its primary run callback
        self._tab_run_actions = {
            0: self._run_auto_process,
            1: self._run_parse,
            2: self._run_build_graph,
            3: self._run_survey,
        }
        # Bind both lowercase and uppercase so Caps Lock does not break it
        self.root.bind("<Control-r>", self._ctrl_r)
        self.root.bind("<Control-R>", self._ctrl_r)

    def _ctrl_r(self, _event) -> None:
        # Trigger the run action for whichever notebook tab is currently visible
        tab_idx = self._nb.index(self._nb.select())
        action  = self._tab_run_actions.get(tab_idx)
        if action:
            action()

    # ── Tab 0 actions — Auto Pilot ────────────────────────────────────────────

    def _run_auto_process(self) -> None:
        game_root = self._dash_game_root.get().strip()
        if not game_root:
            messagebox.showwarning(
                "Missing input",
                "Please select a game root directory first.",
            )
            return

        # Disable the button to prevent double-runs while the chain executes
        self._dash_start_btn.configure(state="disabled", text="⏳  Running…")

        # Snapshot the config so mid-run changes to Settings have no effect
        cfg = dict(self._config)

        self._run_in_thread(
            self._do_auto_process,
            game_root,
            self._dash_do_graph.get(),
            self._dash_do_survey.get(),
            cfg,
            status="Auto Pilot running…",
        )

    def _do_auto_process(
        self,
        game_root: str,
        do_graph:  bool,
        do_survey: bool,
        cfg:       Dict[str, Any],
    ) -> None:
        """
        Sequential automation worker: Parse → (Graph) → (Survey).

        Runs in a background thread.  Progress is logged as:
            "▶  Step N of M — description…"  (start of step)
            "✔  Step N of M: description."   (end of step)
        Each graph exporter call is individually wrapped so a single missing
        dependency or write error does not abort the entire run.

        Parameters
        ----------
        game_root : validated path to the Ren'Py game root directory
        do_graph  : whether to build and export the narrative graph
        do_survey : whether to generate the player survey
        cfg       : snapshot of self._config at the time the run was triggered
        """
        total  = 1 + int(do_graph) + int(do_survey)
        step   = 0
        folder = cfg.get("auto_output_folder", "rensight_output")

        # Place the output folder next to (not inside) the game root
        parent_dir = os.path.dirname(game_root.rstrip("/\\")) or game_root
        output_dir = os.path.join(parent_dir, str(folder))
        json_path  = os.path.join(output_dir, "parsed_script.json")

        try:
            # ── Step 1: Parse ──────────────────────────────────────────────
            step += 1
            logger.info("▶  Step %d of %d — Parsing game scripts in: %s",
                        step, total, game_root)
            self.root.after(0, self._set_busy, f"Step {step} of {total}: Parsing…")

            from vn_parser.renpy_parser import parse_project   # type: ignore[import]

            script = parse_project(
                game_root,
                game_version  = str(cfg.get("auto_game_version", "unknown")),
                context_lines = int(cfg.get("auto_context_lines", 4)),
            )
            os.makedirs(output_dir, exist_ok=True)
            with open(json_path, "w", encoding="utf-8") as fh:
                fh.write(script.to_json())
            logger.info(
                "✔  Step %d of %d: Parsing complete — %d menus, %d labels → %s",
                step, total, script.menu_count, script.label_count, json_path,
            )

            # ── Step 2: Build graph (optional) ─────────────────────────────
            if do_graph:
                step += 1
                logger.info("▶  Step %d of %d — Building narrative graph…", step, total)
                self.root.after(0, self._set_busy,
                                f"Step {step} of {total}: Building graph…")

                from graph_builder.graph_builder import build_graph_from_file   # type: ignore[import]

                graph            = build_graph_from_file(json_path)
                self._last_graph = graph
                graphs_dir       = os.path.join(output_dir, "graphs")

                # Each exporter is isolated — missing binaries warn, not abort
                _EXPORTERS = [
                    ("json", "auto_graph_json",
                     "exporters.graph.json_exporter",     "export_json"),
                    ("dot",  "auto_graph_dot",
                     "exporters.graph.graphviz_exporter", "export_dot"),
                    ("png",  "auto_graph_png",
                     "exporters.graph.graphviz_exporter", "export_png"),
                    ("svg",  "auto_graph_svg",
                     "exporters.graph.graphviz_exporter", "export_svg"),
                    ("html", "auto_graph_html",
                     "exporters.graph.graphviz_exporter", "export_html_interactive"),
                ]
                for fmt, cfg_key, mod_name, fn_name in _EXPORTERS:
                    if not cfg.get(cfg_key):
                        continue
                    try:
                        mod = importlib.import_module(mod_name)
                        getattr(mod, fn_name)(graph, graphs_dir)
                    except Exception as exp_err:
                        logger.warning(
                            "Graph %s export failed (skipping): %s",
                            fmt.upper(), exp_err,
                        )

                logger.info(
                    "✔  Step %d of %d: Graph complete — %d nodes, %d edges.",
                    step, total, graph.label_count, graph.edge_count,
                )

            # ── Step 3: Generate survey (optional) ─────────────────────────
            if do_survey:
                step += 1
                logger.info("▶  Step %d of %d — Generating survey…", step, total)
                self.root.after(0, self._set_busy,
                                f"Step {step} of {total}: Generating survey…")

                from exporters.survey.survey_builder import generate_surveys_from_file   # type: ignore[import]

                # Derive active lists from the config snapshot
                active_formats = [
                    fmt for fmt in ("txt", "html", "markdown", "csv", "json")
                    if cfg.get(f"auto_fmt_{fmt}")
                ]
                active_qs = [
                    qs for qs in _ALL_QUESTION_SETS
                    if cfg.get(f"auto_qs_{qs}")
                ]
                if not active_formats:
                    active_formats = ["html"]   # safe fallback

                written = generate_surveys_from_file(
                    json_path         = json_path,
                    output_dir        = output_dir,
                    formats           = active_formats,
                    question_sets     = active_qs,
                    include_context   = bool(cfg.get("auto_include_context",   True)),
                    randomise_choices = bool(cfg.get("auto_randomise_choices", False)),
                    menu_order        = str(cfg.get("auto_menu_order",         "as_extracted")),
                    game_dir          = game_root,
                    remove_duplicates = bool(cfg.get("auto_remove_duplicates", True)),
                    intro_text        = None,
                    html_group_mode   = str(cfg.get("auto_html_group",         "narrative_block")),
                    html_group_config = None,
                    base_name         = None,
                )
                logger.info(
                    "✔  Step %d of %d: Survey complete — %s",
                    step, total, list(written.values()),
                )

            # ── Done ───────────────────────────────────────────────────────
            logger.info("🎉  Auto Pilot finished.  Output saved to: %s", output_dir)
            self.root.after(
                0, messagebox.showinfo,
                "Automation complete",
                f"All {total} step(s) finished successfully!\n\nOutput saved to:\n{output_dir}",
            )
            self.root.after(
                0, self._autofill_tabs_from_auto, json_path, output_dir, game_root,
            )

        except Exception as exc:
            logger.error(
                "Auto Pilot failed at step %d of %d: %s",
                step, total, exc, exc_info=True,
            )
            self.root.after(
                0, messagebox.showerror,
                "Automation error",
                f"Step {step} of {total} failed:\n\n{exc}",
            )

        finally:
            # Always restore the Start button regardless of outcome
            self.root.after(
                0, self._dash_start_btn.configure,
                {"state": "normal", "text": "▶   START AUTOMATION"},
            )

    def _autofill_tabs_from_auto(
        self,
        json_path:  str,
        output_dir: str,
        game_root:  str,
    ) -> None:
        # Populate the advanced tabs after a successful auto run (main thread only)
        self._graph_json_path.delete(0, tk.END)
        self._graph_json_path.insert(0, json_path)
        self._graph_output_dir.delete(0, tk.END)
        self._graph_output_dir.insert(0, output_dir)

        self._survey_json_path.delete(0, tk.END)
        self._survey_json_path.insert(0, json_path)
        self._survey_output_dir.delete(0, tk.END)
        self._survey_output_dir.insert(0, output_dir)
        self._survey_game_dir.delete(0, tk.END)
        self._survey_game_dir.insert(0, game_root)

    # ── Tab 1 actions ─────────────────────────────────────────────────────────

    def _run_parse(self) -> None:
        game_dir   = self._parse_game_dir.get().strip()
        output_dir = self._parse_output_dir.get().strip()
        if not game_dir:
            messagebox.showwarning("Missing input", "Please select a game directory.")
            return
        if not output_dir:
            messagebox.showwarning("Missing output", "Please select an output directory.")
            return
        version   = self._parse_version.get().strip() or "unknown"
        ctx_lines = int(self._parse_ctx_lines.get())
        logger.info("Parsing game scripts in: %s", game_dir)
        self._run_in_thread(
            self._do_parse, game_dir, output_dir, version, ctx_lines,
            status="Parsing game scripts…",
        )

    def _do_parse(
        self,
        game_dir:   str,
        output_dir: str,
        version:    str,
        ctx_lines:  int,
    ) -> None:
        try:
            from vn_parser.renpy_parser import parse_project   # type: ignore[import]
            script    = parse_project(game_dir, game_version=version,
                                      context_lines=ctx_lines)
            os.makedirs(output_dir, exist_ok=True)
            json_path = os.path.join(output_dir, "parsed_script.json")
            with open(json_path, "w", encoding="utf-8") as fh:
                fh.write(script.to_json())
            logger.info(
                "Parsed %d menus across %d labels → %s",
                script.menu_count, script.label_count, json_path,
            )
            self.root.after(0, self._offer_autofill, json_path, output_dir)
        except Exception as exc:
            logger.error("Parse failed: %s", exc, exc_info=True)
            self.root.after(0, messagebox.showerror, "Parse error", str(exc))

    def _offer_autofill(self, json_path: str, output_dir: str) -> None:
        # Prompt to propagate the new JSON path to Graph and Survey tabs
        if messagebox.askyesno(
            "Parse complete",
            "Parsed successfully.\n\nAuto-fill JSON path in Graph and Survey tabs?",
        ):
            for entry in (self._graph_json_path, self._survey_json_path):
                entry.delete(0, tk.END)
                entry.insert(0, json_path)
            self._graph_output_dir.delete(0, tk.END)
            self._graph_output_dir.insert(0, output_dir)
            self._survey_output_dir.delete(0, tk.END)
            self._survey_output_dir.insert(0, output_dir)

    # ── Tab 2 actions ─────────────────────────────────────────────────────────

    def _run_build_graph(self) -> None:
        json_path  = self._graph_json_path.get().strip()
        output_dir = self._graph_output_dir.get().strip()
        if not json_path:
            messagebox.showwarning("Missing input", "Please select a JSON file.")
            return
        if not output_dir:
            messagebox.showwarning("Missing output", "Please select an output directory.")
            return
        exports = {
            "json": self._graph_export_json.get(),
            "dot":  self._graph_export_dot.get(),
            "png":  self._graph_export_png.get(),
            "svg":  self._graph_export_svg.get(),
            "html": self._graph_export_html.get(),
        }
        logger.info("Building narrative graph from: %s", json_path)
        self._run_in_thread(
            self._do_build_graph, json_path, output_dir, exports,
            status="Building narrative graph…",
        )

    def _do_build_graph(
        self,
        json_path:  str,
        output_dir: str,
        exports:    Dict[str, bool],
    ) -> None:
        try:
            from graph_builder.graph_builder import build_graph_from_file   # type: ignore[import]

            graph            = build_graph_from_file(json_path)
            self._last_graph = graph
            graphs_dir       = os.path.join(output_dir, "graphs")

            # Isolate each format so one failure does not block the others
            _EXPORT_MAP = {
                "json": ("exporters.graph.json_exporter",     "export_json"),
                "dot":  ("exporters.graph.graphviz_exporter", "export_dot"),
                "png":  ("exporters.graph.graphviz_exporter", "export_png"),
                "svg":  ("exporters.graph.graphviz_exporter", "export_svg"),
                "html": ("exporters.graph.graphviz_exporter", "export_html_interactive"),
            }
            for fmt, (mod_name, fn_name) in _EXPORT_MAP.items():
                if not exports.get(fmt):
                    continue
                try:
                    mod = importlib.import_module(mod_name)
                    getattr(mod, fn_name)(graph, graphs_dir)
                except Exception as exp_err:
                    logger.warning(
                        "Graph %s export failed (skipping): %s", fmt.upper(), exp_err,
                    )

            stats = self._format_graph_stats(graph)
            self.root.after(0, self._update_stats_box, stats)
            logger.info(
                "Graph complete: nodes=%d, edges=%d",
                graph.label_count, graph.edge_count,
            )
        except Exception as exc:
            logger.error("Graph build failed: %s", exc, exc_info=True)
            self.root.after(0, messagebox.showerror, "Graph error", str(exc))

    def _show_graph_stats(self) -> None:
        if not self._last_graph:
            messagebox.showinfo("No graph", "Build the graph first.")
            return
        self._update_stats_box("Computing statistics…")
        self._run_in_thread(
            self._do_show_graph_stats, self._last_graph,
            status="Computing graph statistics…",
        )

    def _do_show_graph_stats(self, graph) -> None:
        try:
            stats = self._format_graph_stats(graph)
        except Exception as exc:
            stats = f"Error computing statistics: {exc}"
        self.root.after(0, self._update_stats_box, stats)

    def _format_graph_stats(self, graph) -> str:
        # Build a human-readable statistics summary from the graph object
        has_cycles = graph.has_cycles()
        lines = [
            f"Nodes (labels)    : {graph.label_count}",
            f"Edges             : {graph.edge_count}",
            f"Has cycles        : {has_cycles}",
            f"Labels with menus : {len(graph.labels_with_menus())}",
        ]
        unreachable = graph.unreachable_from("start")
        lines.append(f"Unreachable from \u2018start\u2019: {len(unreachable)}")
        if unreachable[:5]:
            lines.append("  e.g. " + ", ".join(unreachable[:5]))

        _CYCLE_LIMIT = 500
        if has_cycles:
            if graph.label_count <= _CYCLE_LIMIT:
                cycles = graph.find_cycles()
                lines.append(f"Cycles found: {len(cycles)}")
                for c in cycles[:3]:
                    lines.append("  " + " \u2192 ".join(c[:6]))
            else:
                lines.append(
                    f"(Cycle enumeration skipped for graphs > {_CYCLE_LIMIT} nodes)"
                )

        lines += ["", "BFS order (first 20):"]
        bfs = graph.bfs_order("start")
        lines.append("  " + ", ".join(bfs[:20]))
        return "\n".join(lines)

    def _update_stats_box(self, text: str) -> None:
        # Replace the entire stats text box content; must run on the main thread
        self._graph_stats_box.configure(state="normal")
        self._graph_stats_box.delete("1.0", tk.END)
        self._graph_stats_box.insert(tk.END, text)
        self._graph_stats_box.configure(state="disabled")

    # ── Tab 3 actions ─────────────────────────────────────────────────────────

    def _run_survey(self) -> None:
        json_path  = self._survey_json_path.get().strip()
        output_dir = self._survey_output_dir.get().strip()
        if not json_path:
            messagebox.showwarning("Missing input", "Please select a JSON file.")
            return
        if not output_dir:
            messagebox.showwarning("Missing output", "Please select an output directory.")
            return
        formats = [fmt for fmt, var in self._fmt_vars.items() if var.get()]
        if not formats:
            messagebox.showwarning(
                "No formats", "Please select at least one output format.",
            )
            return
        selected_qs = [qs for qs, var in self._qs_vars.items() if var.get()]
        game_dir    = self._survey_game_dir.get().strip() or None
        order       = self._menu_order.get()
        intro_text  = self._survey_intro.get("1.0", tk.END).strip()
        html_group  = self._html_group_mode.get()
        cfg_path    = (
            self._grp_config_path.get().strip()
            if html_group == "config" else ""
        )
        base_name   = self._survey_base_name.get().strip() or None
        logger.info(
            "Generating surveys: formats=%s, order=%s, html_group=%s",
            formats, order, html_group,
        )
        self._run_in_thread(
            self._do_survey,
            json_path, output_dir, formats, selected_qs,
            self._include_context.get(), self._randomise_choices.get(),
            self._remove_duplicates.get(), order, game_dir, intro_text,
            html_group, cfg_path, base_name,
            status="Generating survey…",
        )

    def _do_survey(
        self,
        json_path:   str,
        output_dir:  str,
        formats:     List[str],
        selected_qs: List[str],
        include_ctx: bool,
        randomise:   bool,
        dedup:       bool,
        order:       str,
        game_dir:    Optional[str],
        intro_text:  str,
        html_group:  str = "narrative_block",
        cfg_path:    str = "",
        base_name:   Optional[str] = None,
    ) -> None:
        try:
            from exporters.survey.survey_builder import generate_surveys_from_file   # type: ignore[import]

            html_group_config = None
            if html_group == "config" and cfg_path:
                try:
                    with open(cfg_path, encoding="utf-8") as _fh:
                        html_group_config = json.load(_fh)
                except Exception as cfg_err:
                    logger.warning("Could not load group config: %s", cfg_err)

            written = generate_surveys_from_file(
                json_path         = json_path,
                output_dir        = output_dir,
                formats           = formats,
                question_sets     = selected_qs if selected_qs else [],
                include_context   = include_ctx,
                randomise_choices = randomise,
                menu_order        = order,
                game_dir          = game_dir,
                remove_duplicates = dedup,
                intro_text        = intro_text or None,
                html_group_mode   = html_group,
                html_group_config = html_group_config,
                base_name         = base_name,
            )
            logger.info("Surveys generated: %s", list(written.values()))
            self.root.after(
                0, messagebox.showinfo,
                "Done",
                f"Generated {len(written)} file(s):\n" + "\n".join(written.values()),
            )
        except Exception as exc:
            logger.error("Survey generation failed: %s", exc, exc_info=True)
            self.root.after(0, messagebox.showerror, "Survey error", str(exc))

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Enter the Tk main event loop."""
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def launch() -> None:
    """Create the root Tk window and start Ren'Sight."""
    # className sets WM_CLASS — pair with a .desktop StartupWMClass entry for
    # correct GNOME/KDE dock-icon association.
    root = tk.Tk(className="RenSight")
    app  = RenSightGUI(root)
    app.run()


if __name__ == "__main__":
    launch()
