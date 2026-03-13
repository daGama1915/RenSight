"""
pipeline/pipeline_stages.py
-----------------------------
Enum and result dataclasses for each stage of the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


class PipelineStage(Enum):
    PARSE    = auto()   # vn_parser → ParsedScript
    GRAPH    = auto()   # graph_builder → NarrativeGraph
    SURVEY   = auto()   # exporters/survey → survey files
    ANALYSIS = auto()   # analysis passes (future)
    EXPORT   = auto()   # graph exporters


@dataclass
class StageResult:
    """Result record for a single pipeline stage."""
    stage:    PipelineStage
    success:  bool
    output:   Any           = None
    error:    Optional[str] = None
    messages: list          = field(default_factory=list)
