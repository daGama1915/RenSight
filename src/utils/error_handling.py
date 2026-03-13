"""utils/error_handling.py — shared exception types."""
class VNToolError(Exception): pass
class ParserError(VNToolError): pass
class GraphError(VNToolError): pass
class ExportError(VNToolError): pass
