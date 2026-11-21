"""Integration tests for graph_builder.py with formula_parser integration and cycle detection."""



class TestCycleDetection:
    """Verify that circular references are detected and reported."""

    def test_simple_cycle_detected(self):
        """A1=B1, B1=A1 should be detected as a cycle."""
        from xlens.graph_builder import build_graph
        cells = {
            ("Sheet1", "A1"): {
                "sheet": "Sheet1", "cell_ref": "A1", "row": 1, "col": 1,
                "raw_value": None, "formula": "=B1", "cached_value": None,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
            ("Sheet1", "B1"): {
                "sheet": "Sheet1", "cell_ref": "B1", "row": 1, "col": 2,
                "raw_value": None, "formula": "=A1", "cached_value": None,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
        }
        graph, stats = build_graph(cells)

        assert stats["has_circular_refs"] is True
        assert stats["circular_ref_count"] >= 1
        assert len(stats["circular_references"]) >= 1
        # Both cells should be in the circular ref cells
        circ_cells = set(stats["circular_ref_cells"])
        assert "Sheet1!A1" in circ_cells
        assert "Sheet1!B1" in circ_cells

    def test_no_cycle_in_dag(self):
        """Linear chain A1->B1->C1 should have no cycles."""
        from xlens.graph_builder import build_graph
        cells = {
            ("Sheet1", "A1"): {
                "sheet": "Sheet1", "cell_ref": "A1", "row": 1, "col": 1,
                "raw_value": 10, "formula": None, "cached_value": 10,
                "data_type": "n", "row_label": "", "classification": "deal_input",
            },
            ("Sheet1", "B1"): {
                "sheet": "Sheet1", "cell_ref": "B1", "row": 1, "col": 2,
                "raw_value": None, "formula": "=A1*2", "cached_value": 20,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
            ("Sheet1", "C1"): {
                "sheet": "Sheet1", "cell_ref": "C1", "row": 1, "col": 3,
                "raw_value": None, "formula": "=B1+1", "cached_value": 21,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
        }
        graph, stats = build_graph(cells)

        assert stats["has_circular_refs"] is False
        assert stats["circular_ref_count"] == 0
        assert stats["circular_references"] == []

    def test_cycle_edges_preserved_in_graph(self):
        """Circular edges should remain in the graph (not removed)."""
        from xlens.graph_builder import build_graph
        cells = {
            ("Sheet1", "A1"): {
                "sheet": "Sheet1", "cell_ref": "A1", "row": 1, "col": 1,
                "raw_value": None, "formula": "=B1", "cached_value": None,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
            ("Sheet1", "B1"): {
                "sheet": "Sheet1", "cell_ref": "B1", "row": 1, "col": 2,
                "raw_value": None, "formula": "=A1", "cached_value": None,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
        }
        graph, stats = build_graph(cells)

        # Both edges forming the cycle should exist
        assert graph.has_edge("Sheet1!B1", "Sheet1!A1")
        assert graph.has_edge("Sheet1!A1", "Sheet1!B1")

    def test_cycle_has_length_and_cells(self):
        """Each detected cycle should have 'cycle' and 'length' keys."""
        from xlens.graph_builder import build_graph
        cells = {
            ("Sheet1", "A1"): {
                "sheet": "Sheet1", "cell_ref": "A1", "row": 1, "col": 1,
                "raw_value": None, "formula": "=B1", "cached_value": None,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
            ("Sheet1", "B1"): {
                "sheet": "Sheet1", "cell_ref": "B1", "row": 1, "col": 2,
                "raw_value": None, "formula": "=A1", "cached_value": None,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
        }
        graph, stats = build_graph(cells)

        cycle_entry = stats["circular_references"][0]
        assert "cycle" in cycle_entry
        assert "length" in cycle_entry
        assert cycle_entry["length"] == len(cycle_entry["cycle"])

    def test_three_node_cycle(self):
        """A1->B1->C1->A1 three-node cycle."""
        from xlens.graph_builder import build_graph
        cells = {
            ("Sheet1", "A1"): {
                "sheet": "Sheet1", "cell_ref": "A1", "row": 1, "col": 1,
                "raw_value": None, "formula": "=C1", "cached_value": None,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
            ("Sheet1", "B1"): {
                "sheet": "Sheet1", "cell_ref": "B1", "row": 1, "col": 2,
                "raw_value": None, "formula": "=A1", "cached_value": None,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
            ("Sheet1", "C1"): {
                "sheet": "Sheet1", "cell_ref": "C1", "row": 1, "col": 3,
                "raw_value": None, "formula": "=B1", "cached_value": None,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
        }
        graph, stats = build_graph(cells)

        assert stats["has_circular_refs"] is True
        circ_cells = set(stats["circular_ref_cells"])
        assert "Sheet1!A1" in circ_cells
        assert "Sheet1!B1" in circ_cells
        assert "Sheet1!C1" in circ_cells


class TestNamedRangeEdges:
    """Verify that named range references create graph edges."""

    def test_named_range_creates_edge(self):
        """A formula referencing a named range should create an edge after resolution."""
        from xlens.graph_builder import build_graph

        # Cell C1 has formula =Price*2, Price is named range pointing to B5
        cells = {
            ("Sheet1", "B5"): {
                "sheet": "Sheet1", "cell_ref": "B5", "row": 5, "col": 2,
                "raw_value": 100000, "formula": None, "cached_value": 100000,
                "data_type": "n", "row_label": "Purchase Price", "classification": "deal_input",
            },
            ("Sheet1", "C1"): {
                "sheet": "Sheet1", "cell_ref": "C1", "row": 1, "col": 3,
                "raw_value": None, "formula": "=Price*2", "cached_value": 200000,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
        }
        named_range_map = {
            "Price": [("Sheet1", "B5")],
        }

        graph, stats = build_graph(cells, named_range_map=named_range_map)

        # There should be an edge from B5 to C1
        assert graph.has_edge("Sheet1!B5", "Sheet1!C1"), \
            "Named range 'Price' should resolve to edge Sheet1!B5 -> Sheet1!C1"

    def test_named_range_no_map_no_crash(self):
        """Without named_range_map, named range formulas shouldn't crash."""
        from xlens.graph_builder import build_graph

        cells = {
            ("Sheet1", "C1"): {
                "sheet": "Sheet1", "cell_ref": "C1", "row": 1, "col": 3,
                "raw_value": None, "formula": "=Price*2", "cached_value": 200000,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
        }

        graph, stats = build_graph(cells)
        # Should not crash, just won't have the named range edge
        assert graph.has_node("Sheet1!C1")


class TestParserWarnings:
    """Verify that parser warnings are collected in stats."""

    def test_warnings_in_stats(self):
        """Parser warnings should be available in stats dict."""
        from xlens.graph_builder import build_graph

        cells = {
            ("Sheet1", "A1"): {
                "sheet": "Sheet1", "cell_ref": "A1", "row": 1, "col": 1,
                "raw_value": None, "formula": "=SUM(A:D)", "cached_value": 0,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
        }

        graph, stats = build_graph(cells)

        assert "parser_warnings" in stats
        assert isinstance(stats["parser_warnings"], list)
        # Column range A:D should generate a warning
        assert any("collapsed" in w.lower() or "column range" in w.lower()
                    for w in stats["parser_warnings"])

    def test_no_warnings_for_simple_refs(self):
        """Simple cell refs should produce no warnings."""
        from xlens.graph_builder import build_graph

        cells = {
            ("Sheet1", "A1"): {
                "sheet": "Sheet1", "cell_ref": "A1", "row": 1, "col": 1,
                "raw_value": 10, "formula": None, "cached_value": 10,
                "data_type": "n", "row_label": "", "classification": "deal_input",
            },
            ("Sheet1", "B1"): {
                "sheet": "Sheet1", "cell_ref": "B1", "row": 1, "col": 2,
                "raw_value": None, "formula": "=A1+1", "cached_value": 11,
                "data_type": "f", "row_label": "", "classification": "derived",
            },
        }

        graph, stats = build_graph(cells)

        assert stats["parser_warnings"] == []


class TestGraphBuilderUsesFormulaParser:
    """Verify graph_builder uses formula_parser instead of local parsing."""

    def test_no_local_extract_all_refs(self):
        """graph_builder.py should not have _extract_all_refs."""
        import xlens.graph_builder as mod
        assert not hasattr(mod, "_extract_all_refs"), \
            "graph_builder.py still has local _extract_all_refs"

    def test_no_local_expand_range(self):
        """graph_builder.py should not have _expand_range."""
        import xlens.graph_builder as mod
        assert not hasattr(mod, "_expand_range"), \
            "graph_builder.py still has local _expand_range"

    def test_no_local_col_helpers(self):
        """graph_builder.py should not have _col_to_num or _num_to_col."""
        import xlens.graph_builder as mod
        assert not hasattr(mod, "_col_to_num"), \
            "graph_builder.py still has local _col_to_num"
        assert not hasattr(mod, "_num_to_col"), \
            "graph_builder.py still has local _num_to_col"
