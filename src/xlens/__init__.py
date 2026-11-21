"""xlens - Excel model reverse-engineering and analysis toolkit."""
__version__ = "0.2.0"
from xlens.assumption_analyzer import analyze_assumptions
from xlens.complexity_scorer import score_complexity
from xlens.extractor import extract_cells
from xlens.flow_builder import build_flow
from xlens.formula_parser import extract_references
from xlens.graph_builder import build_graph, export_graph_json
from xlens.hardcode_detector import detect_hardcodes
from xlens.kpi_identifier import identify_kpis
from xlens.report_generator import generate_report

__all__ = [
    "analyze_assumptions",
    "build_flow",
    "build_graph",
    "detect_hardcodes",
    "export_graph_json",
    "extract_cells",
    "extract_references",
    "generate_report",
    "identify_kpis",
    "score_complexity",
]
