"""Tests for complexity_scorer module."""

import networkx as nx

from xlens.complexity_scorer import score_complexity


class TestScoreComplexityReturnShape:
    """Test the shape and types of the returned dict."""

    def test_returns_required_keys(self):
        G = nx.DiGraph()
        result = score_complexity({}, G)
        assert "score" in result
        assert "grade" in result
        assert "metrics" in result
        assert "critical_path" in result
        assert "bottleneck_cells" in result

    def test_score_is_int_in_range(self):
        G = nx.DiGraph()
        result = score_complexity({}, G)
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100

    def test_grade_is_valid(self):
        G = nx.DiGraph()
        result = score_complexity({}, G)
        assert result["grade"] in ("A", "B", "C", "D", "F")

    def test_critical_path_is_list_of_strings(self):
        G = nx.DiGraph()
        G.add_node("S!A1", sheet="S", cell_ref="A1", formula=None)
        G.add_node("S!A2", sheet="S", cell_ref="A2", formula="=A1")
        G.add_edge("S!A1", "S!A2")
        result = score_complexity({}, G)
        assert isinstance(result["critical_path"], list)
        for item in result["critical_path"]:
            assert isinstance(item, str)

    def test_bottleneck_cells_max_5(self):
        # Build graph with many nodes
        G = nx.DiGraph()
        for i in range(20):
            G.add_node(f"S!A{i+1}", sheet="S", cell_ref=f"A{i+1}", formula=None)
        for i in range(19):
            G.add_edge(f"S!A{i+1}", f"S!A{i+2}")
        result = score_complexity({}, G)
        assert len(result["bottleneck_cells"]) <= 5

    def test_metrics_have_raw_and_normalized(self):
        G = nx.DiGraph()
        G.add_node("S!A1", sheet="S", cell_ref="A1", formula=None)
        G.add_node("S!A2", sheet="S", cell_ref="A2", formula="=A1")
        G.add_edge("S!A1", "S!A2")
        result = score_complexity({}, G)
        for name, metric in result["metrics"].items():
            assert "raw" in metric, f"Metric '{name}' missing 'raw' key"
            assert "normalized" in metric, f"Metric '{name}' missing 'normalized' key"


class TestEmptyGraph:
    """Test behavior with empty/minimal graphs."""

    def test_empty_graph_score_zero(self):
        G = nx.DiGraph()
        result = score_complexity({}, G)
        assert result["score"] == 0
        assert result["grade"] == "A"

    def test_empty_graph_critical_path_empty(self):
        G = nx.DiGraph()
        result = score_complexity({}, G)
        assert result["critical_path"] == []

    def test_empty_graph_bottleneck_empty(self):
        G = nx.DiGraph()
        result = score_complexity({}, G)
        assert result["bottleneck_cells"] == []


class TestSimpleChain:
    """Test with a simple linear chain A->B->C."""

    def _make_chain(self, length=3):
        G = nx.DiGraph()
        cells = {}
        for i in range(length):
            node = f"S!A{i+1}"
            G.add_node(node, sheet="S", cell_ref=f"A{i+1}", formula=None)
            cells[("S", f"A{i+1}")] = {
                "formula": f"=A{i}" if i > 0 else None,
                "sheet": "S",
            }
        for i in range(length - 1):
            G.add_edge(f"S!A{i+1}", f"S!A{i+2}")
        return cells, G

    def test_simple_chain_low_score(self):
        cells, G = self._make_chain(3)
        result = score_complexity(cells, G)
        assert result["score"] < 30, "Simple 3-node chain should have low complexity"

    def test_simple_chain_grade_a_or_b(self):
        cells, G = self._make_chain(3)
        result = score_complexity(cells, G)
        assert result["grade"] in ("A", "B")


class TestCrossSheetEdgeRatio:
    """Test cross-sheet edge detection."""

    def test_all_same_sheet_ratio_zero(self):
        G = nx.DiGraph()
        G.add_node("S!A1", sheet="S", cell_ref="A1", formula=None)
        G.add_node("S!A2", sheet="S", cell_ref="A2", formula="=A1")
        G.add_edge("S!A1", "S!A2")
        cells = {
            ("S", "A1"): {"formula": None, "sheet": "S"},
            ("S", "A2"): {"formula": "=A1", "sheet": "S"},
        }
        result = score_complexity(cells, G)
        assert result["metrics"]["cross_sheet_ratio"]["raw"] == 0.0

    def test_all_cross_sheet_ratio_one(self):
        G = nx.DiGraph()
        G.add_node("S1!A1", sheet="S1", cell_ref="A1", formula=None)
        G.add_node("S2!A1", sheet="S2", cell_ref="A1", formula="=S1!A1")
        G.add_edge("S1!A1", "S2!A1")
        cells = {
            ("S1", "A1"): {"formula": None, "sheet": "S1"},
            ("S2", "A1"): {"formula": "=S1!A1", "sheet": "S2"},
        }
        result = score_complexity(cells, G)
        assert result["metrics"]["cross_sheet_ratio"]["raw"] == 1.0


class TestHeavilyConnectedGraph:
    """Test that complex graphs produce high scores."""

    def test_dense_graph_high_score(self):
        G = nx.DiGraph()
        # Many cross-sheet edges, high fan-in/fan-out
        sheets = ["S1", "S2", "S3"]
        for s in sheets:
            for i in range(10):
                node = f"{s}!A{i+1}"
                G.add_node(node, sheet=s, cell_ref=f"A{i+1}", formula="=SUM(...)")
        # Connect heavily across sheets
        for s1 in sheets:
            for s2 in sheets:
                if s1 != s2:
                    for i in range(10):
                        G.add_edge(f"{s1}!A{i+1}", f"{s2}!A{(i+3) % 10 + 1}")
        cells = {}
        for s in sheets:
            for i in range(10):
                cells[(s, f"A{i+1}")] = {
                    "formula": f"=SUM(A1:A{i})" if i > 0 else None,
                    "sheet": s,
                }
        result = score_complexity(cells, G)
        # Cycles zero out DAG metrics, but cross-sheet ratio, fan-in/out,
        # cyclomatic, and unique_formula_ratio still contribute meaningfully.
        assert result["score"] > 15, "Dense cross-sheet graph should have notable complexity"
