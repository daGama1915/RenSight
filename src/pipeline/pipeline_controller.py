"""
pipeline/pipeline_controller.py
---------------------------------
Orchestrates the full v0.2 processing pipeline:

    vn_parser  →  graph_builder  →  survey exporter  →  graph exporter

Each stage is optional; the controller tracks successes and failures.

Usage::

    from pipeline.pipeline_controller import PipelineController

    ctrl = PipelineController(
        game_dir    = "/path/to/game",
        output_dir  = "/path/to/output",
        game_version = "0.4.2",
    )
    ctrl.run_all()
    print(ctrl.summary())
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .pipeline_stages          import PipelineStage, StageResult
from vn_parser.renpy_parser  import parse_project
from ir.parsed_script        import ParsedScript
from ir.narrative_graph      import NarrativeGraph
from graph_builder.graph_builder import build_graph

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """All configurable parameters for a pipeline run."""
    game_dir:          str
    output_dir:        str         = "output"
    game_version:      str         = "unknown"
    context_lines:     int         = 4
    # Survey options
    survey_formats:    Sequence[str]            = field(default_factory=lambda: ["txt", "html"])
    question_sets:     Optional[Sequence[str]]  = None
    include_context:   bool                     = True
    randomise_choices: bool                     = False
    menu_order:        str                      = "as_extracted"
    remove_duplicates: bool                     = True
    # Graph export options
    export_graph_json:   bool = True
    export_graph_dot:    bool = False
    export_graph_png:    bool = False
    export_graph_svg:    bool = False


class PipelineController:
    """
    Runs the full pipeline and records results from each stage.

    Attributes:
        config:    PipelineConfig with all run parameters.
        script:    ParsedScript produced by the parse stage (set after run_parse).
        graph:     NarrativeGraph produced by the graph stage (set after run_graph).
        results:   List of StageResult, one per completed stage.
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config  = config
        self.script:  Optional[ParsedScript]   = None
        self.graph:   Optional[NarrativeGraph] = None
        self.results: List[StageResult]        = []

    # ------------------------------------------------------------------
    # Stage runners
    # ------------------------------------------------------------------

    def run_parse(self) -> StageResult:
        """Run the parser pipeline and populate ``self.script``."""
        logger.info("Pipeline: PARSE stage")
        try:
            json_out = os.path.join(self.config.output_dir, "parsed_script.json")
            self.script = parse_project(
                game_dir      = self.config.game_dir,
                output_path   = json_out,
                game_version  = self.config.game_version,
                context_lines = self.config.context_lines,
            )
            res = StageResult(
                stage   = PipelineStage.PARSE,
                success = True,
                output  = self.script,
                messages = [
                    f"Parsed {self.script.label_count} labels, "
                    f"{self.script.menu_count} menus, "
                    f"{len(self.script.jumps)} jumps.",
                    f"Output: {json_out}",
                ],
            )
        except Exception as exc:
            logger.exception("PARSE stage failed.")
            res = StageResult(
                stage   = PipelineStage.PARSE,
                success = False,
                error   = str(exc),
            )
        self.results.append(res)
        return res

    def run_graph(self) -> StageResult:
        """Build the narrative graph from ``self.script``."""
        logger.info("Pipeline: GRAPH stage")
        if self.script is None:
            res = StageResult(
                stage   = PipelineStage.GRAPH,
                success = False,
                error   = "PARSE stage must run first.",
            )
            self.results.append(res)
            return res
        try:
            self.graph = build_graph(self.script)
            res = StageResult(
                stage   = PipelineStage.GRAPH,
                success = True,
                output  = self.graph,
                messages = [
                    f"Graph: {self.graph.label_count} nodes, "
                    f"{self.graph.edge_count} edges, "
                    f"cycles={self.graph.has_cycles()}.",
                ],
            )
        except Exception as exc:
            logger.exception("GRAPH stage failed.")
            res = StageResult(
                stage   = PipelineStage.GRAPH,
                success = False,
                error   = str(exc),
            )
        self.results.append(res)
        return res

    def run_survey(self) -> StageResult:
        """Generate survey files from ``self.script``."""
        logger.info("Pipeline: SURVEY stage")
        if self.script is None:
            res = StageResult(
                stage   = PipelineStage.SURVEY,
                success = False,
                error   = "PARSE stage must run first.",
            )
            self.results.append(res)
            return res
        try:
            from exporters.survey.survey_builder import generate_surveys
            survey_dir = os.path.join(self.config.output_dir, "surveys")
            written = generate_surveys(
                script            = self.script,
                output_dir        = survey_dir,
                formats           = self.config.survey_formats,
                question_sets     = self.config.question_sets,
                include_context   = self.config.include_context,
                randomise_choices = self.config.randomise_choices,
                menu_order        = self.config.menu_order,
                graph             = self.graph,
                remove_duplicates = self.config.remove_duplicates,
            )
            res = StageResult(
                stage   = PipelineStage.SURVEY,
                success = True,
                output  = written,
                messages = [f"Survey files: {list(written.values())}"],
            )
        except Exception as exc:
            logger.exception("SURVEY stage failed.")
            res = StageResult(
                stage   = PipelineStage.SURVEY,
                success = False,
                error   = str(exc),
            )
        self.results.append(res)
        return res

    def run_graph_export(self) -> StageResult:
        """Export the narrative graph to requested formats."""
        logger.info("Pipeline: EXPORT (graph) stage")
        if self.graph is None:
            res = StageResult(
                stage   = PipelineStage.EXPORT,
                success = False,
                error   = "GRAPH stage must run first.",
            )
            self.results.append(res)
            return res
        try:
            from exporters.graph.json_exporter     import export_json, export_graphml
            from exporters.graph.graphviz_exporter import export_dot, export_png, export_svg

            graphs_dir = os.path.join(self.config.output_dir, "graphs")
            outputs: Dict[str, Optional[str]] = {}

            if self.config.export_graph_json:
                outputs["json"] = export_json(self.graph, graphs_dir)
            if self.config.export_graph_dot:
                outputs["dot"] = export_dot(self.graph, graphs_dir)
            if self.config.export_graph_png:
                outputs["png"] = export_png(self.graph, graphs_dir)
            if self.config.export_graph_svg:
                outputs["svg"] = export_svg(self.graph, graphs_dir)

            res = StageResult(
                stage   = PipelineStage.EXPORT,
                success = True,
                output  = outputs,
                messages = [f"Graph exports: {outputs}"],
            )
        except Exception as exc:
            logger.exception("EXPORT stage failed.")
            res = StageResult(
                stage   = PipelineStage.EXPORT,
                success = False,
                error   = str(exc),
            )
        self.results.append(res)
        return res

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def run_all(self) -> List[StageResult]:
        """Run parse → graph → survey → graph export in sequence."""
        self.run_parse()
        if not self.results[-1].success:
            return self.results
        self.run_graph()
        self.run_survey()
        if self.graph is not None:
            self.run_graph_export()
        return self.results

    def summary(self) -> str:
        lines = ["Pipeline summary:"]
        for r in self.results:
            status = "✓" if r.success else "✗"
            lines.append(f"  {status} {r.stage.name}")
            for msg in r.messages:
                lines.append(f"      {msg}")
            if r.error:
                lines.append(f"      ERROR: {r.error}")
        return "\n".join(lines)
