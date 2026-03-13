"""
main.py
-------
Entry point for the VN Narrative Tool v0.2.

Modes
-----
GUI mode (default):
    python main.py
    python main.py --gui

CLI — full pipeline (parse + graph + survey):
    python main.py --cli --game-dir ./game --output ./output

CLI — parse only:
    python main.py --cli --game-dir ./game --output ./output --parse-only

CLI — survey from existing JSON:
    python main.py --cli --input ./output/parsed_script.json \\
                   --output ./output/surveys --format txt html \\
                   --question-sets clarity preference

This file contains no business logic; it delegates everything to backend
modules.
"""

import argparse
import logging
import os
import sys

# ---------------------------------------------------------------------------
# Ensure src/ is on sys.path regardless of the working directory.
# ---------------------------------------------------------------------------

_ROOT   = os.path.dirname(os.path.abspath(__file__))
_SRC    = os.path.join(_ROOT, "src")
for _p in (_ROOT, _SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level  = level,
        format = "%(levelname)-8s %(name)s — %(message)s",
        stream = sys.stdout,
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog        = "vn_narrative_tool",
        description = "VN Narrative Tool v0.2 — parse Ren'Py scripts, build narrative graphs, generate surveys.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = """\
    Examples
    --------
    Launch GUI:
        python main.py

    Full pipeline (parse + graph + survey):
        python main.py --cli --game-dir ./game --output ./output

    Survey from existing JSON (txt + html):
        python main.py --cli --input ./output/parsed_script.json \\
                        --output ./surveys --format txt html

    Specify question sets:
        python main.py --cli --input menus.json --output surveys \\
                     --format html --question-sets clarity preference
        """,
    )

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--gui", dest="mode", action="store_const", const="gui",
                      help="Launch GUI (default).")
    mode.add_argument("--cli", dest="mode", action="store_const", const="cli",
                      help="Run in headless CLI mode.")
    p.set_defaults(mode="gui")

    # --- Parse options ---
    p.add_argument("--game-dir",    metavar="DIR",
                   help="Root directory of the Ren'Py project.")
    p.add_argument("--game-version", default="unknown",
                   help="Version string embedded in output (default: unknown).")
    p.add_argument("--context-lines", type=int, default=4,
                   help="Dialogue lines to capture before each menu (default: 4).")
    p.add_argument("--parse-only", action="store_true",
                   help="Parse only; skip graph build and survey generation.")

    # --- Shared options ---
    p.add_argument("--input",  metavar="JSON",
                   help="Path to an existing parsed_script.json (skips parse stage).")
    p.add_argument("--output", default="output",
                   help="Output directory (default: output).")

    # --- Survey options ---
    p.add_argument("--format", nargs="+", default=["txt", "html"],
                   metavar="FMT", dest="formats",
                   help="Output format(s): txt markdown csv json html.")
    p.add_argument("--question-sets", nargs="*", default=None,
                   metavar="SET", dest="question_sets",
                   help="Question set names (omit for all; pass nothing for universals only).")
    p.add_argument("--no-context",   action="store_true",
                   help="Omit dialogue context from surveys.")
    p.add_argument("--randomise",    action="store_true",
                   help="Randomise choice order in surveys.")
    p.add_argument("--no-dedup",     action="store_true",
                   help="Keep duplicate menus (deduplication is on by default).")
    p.add_argument("--menu-order",   default="as_extracted",
                   choices=["as_extracted", "file_line", "label_alpha",
                            "choice_id", "narrative_flow"],
                   help="Survey menu ordering mode.")

    # --- Graph export options ---
    p.add_argument("--graph-json",  action="store_true",
                   help="Export narrative graph as JSON (default if any graph export active).")
    p.add_argument("--graph-dot",   action="store_true",
                   help="Export narrative graph as Graphviz DOT source.")
    p.add_argument("--graph-png",   action="store_true",
                   help="Export narrative graph as PNG (requires graphviz package).")
    p.add_argument("--graph-svg",   action="store_true",
                   help="Export narrative graph as SVG (requires graphviz package).")

    p.add_argument("--verbose", "-v", action="store_true",
                   help="Enable DEBUG logging.")

    return p


# ---------------------------------------------------------------------------
# GUI launcher
# ---------------------------------------------------------------------------

def _launch_gui() -> None:
    try:
        import tkinter as tk
    except ImportError:
        print("ERROR: Tkinter is not available on this system.", file=sys.stderr)
        sys.exit(1)

    # GUI module path is project_root/gui/
    gui_dir = os.path.join(_ROOT, "gui")
    if gui_dir not in sys.path:
        sys.path.insert(0, gui_dir)

    from rensight_gui import launch
    launch()


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

def _run_cli(args: argparse.Namespace) -> None:
    from pipeline.pipeline_controller import PipelineController, PipelineConfig

    # ---------------------------------------------------------------- parse
    if args.input:
        # Skip parse stage — load existing JSON
        import json
        from ir.parsed_script import ParsedScript

        logger = logging.getLogger("cli")
        logger.info("Loading existing JSON: %s", args.input)

        with open(args.input, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        if "labels" in data:
            script = ParsedScript.from_dict(data)
        else:
            script = ParsedScript.from_legacy_json(data)

        # Build graph, then generate surveys
        from graph_builder.graph_builder import build_graph
        from exporters.survey.survey_builder import generate_surveys

        graph   = build_graph(script)
        written = generate_surveys(
            script            = script,
            output_dir        = args.output,
            formats           = args.formats,
            question_sets     = args.question_sets,
            include_context   = not args.no_context,
            randomise_choices = args.randomise,
            menu_order        = args.menu_order,
            graph             = graph,
            remove_duplicates = not args.no_dedup,
        )
        for fmt, path in written.items():
            logger.info("  %-10s → %s", fmt, path)
        return

    # ---------------------------------------------------------------- full pipeline
    if not args.game_dir:
        print("ERROR: Specify --game-dir (or --input for an existing JSON).",
              file=sys.stderr)
        sys.exit(1)

    any_graph_export = args.graph_json or args.graph_dot or args.graph_png or args.graph_svg
    # Default: always export graph JSON unless explicitly suppressed
    do_graph_json = args.graph_json or not any_graph_export

    config = PipelineConfig(
        game_dir          = args.game_dir,
        output_dir        = args.output,
        game_version      = args.game_version,
        context_lines     = args.context_lines,
        survey_formats    = args.formats,
        question_sets     = args.question_sets,
        include_context   = not args.no_context,
        randomise_choices = args.randomise,
        menu_order        = args.menu_order,
        remove_duplicates = not args.no_dedup,
        export_graph_json = do_graph_json,
        export_graph_dot  = args.graph_dot,
        export_graph_png  = args.graph_png,
        export_graph_svg  = args.graph_svg,
    )

    ctrl = PipelineController(config)

    if args.parse_only:
        ctrl.run_parse()
    else:
        ctrl.run_all()

    print(ctrl.summary())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    _setup_logging(args.verbose if hasattr(args, "verbose") else False)

    if args.mode == "cli":
        _run_cli(args)
    else:
        _launch_gui()


if __name__ == "__main__":
    main()
