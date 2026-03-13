"""
config/constants.py
--------------------
Shared constants for the vn_narrative_tool.
"""

# Application info
APP_NAME    = "VN Narrative Tool"
APP_VERSION = "0.2.0"

# Default pipeline values
DEFAULT_CONTEXT_LINES  = 6
DEFAULT_GAME_VERSION   = "unknown"
DEFAULT_OUTPUT_DIR     = "output"
DEFAULT_SURVEY_DIR     = "output/surveys"
DEFAULT_GRAPHS_DIR     = "output/graphs"

# Parser
ENCODING_PRIMARY   = "utf-8"
ENCODING_FALLBACK  = "latin-1"
INDENT_UNIT        = 4          # spaces per indent level

# Survey
DEFAULT_FORMATS    = ("txt", "html")
