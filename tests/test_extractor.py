"""Integration tests for extractor.py with formula_parser integration."""



class TestExtractCellsMergedCells:
    """Verify that merged cell references redirect to anchor cells."""

    def test_merged_cell_ref_redirects_to_anchor(self):
        """A formula referencing a non-anchor merged cell should redirect to anchor."""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"

        # Put a value in A1 and merge A1:A3
        ws["A1"] = "Header"
        ws.merge_cells("A1:A3")

        # Put a formula in B1 that references A2 (non-anchor of merged range)
        ws["B1"] = "=A2+1"

        # Save to temp file, load via extract_cells
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name
        wb.save(path)
        wb.close()

        try:
            from xlens.extractor import extract_cells
            cells, context = extract_cells(path)

            # The extraction should have produced a context with merged cell info
            assert "merged_cell_maps" in context
            # Sheet1 should have merged cell redirects
            assert "Sheet1" in context["merged_cell_maps"]
            # A2 (row=2, col=1) should redirect to A1 (row=1, col=1)
            assert (2, 1) in context["merged_cell_maps"]["Sheet1"]
            assert context["merged_cell_maps"]["Sheet1"][(2, 1)] == (1, 1)
        finally:
            os.unlink(path)

    def test_extraction_does_not_crash_on_merged_cells(self):
        """extract_cells should not crash when workbook has merged cells."""
        import os
        import tempfile

        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws["A1"] = "Merged"
        ws.merge_cells("A1:C1")
        ws["A2"] = "=A1"
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name
        wb.save(path)
        wb.close()

        try:
            from xlens.extractor import extract_cells
            cells, context = extract_cells(path)
            assert len(cells) > 0
        finally:
            os.unlink(path)


class TestExtractCellsNamedRanges:
    """Verify that named range info is extracted and returned."""

    def test_named_range_map_in_context(self):
        """extract_cells should return a named_range_map in context."""
        import os
        import tempfile

        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws["B5"] = 100000

        # Create a defined name
        from openpyxl.workbook.defined_name import DefinedName
        defn = DefinedName("Price", attr_text="Sheet1!$B$5")
        wb.defined_names.add(defn)

        ws["C1"] = "=Price*2"

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name
        wb.save(path)
        wb.close()

        try:
            from xlens.extractor import extract_cells
            cells, context = extract_cells(path)
            assert "named_range_map" in context
            assert "Price" in context["named_range_map"]
        finally:
            os.unlink(path)

    def test_parser_warnings_in_context(self):
        """extract_cells should return parser_warnings in context."""
        import os
        import tempfile

        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws["A1"] = 1
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name
        wb.save(path)
        wb.close()

        try:
            from xlens.extractor import extract_cells
            cells, context = extract_cells(path)
            assert "parser_warnings" in context
            assert isinstance(context["parser_warnings"], list)
        finally:
            os.unlink(path)


class TestExtractCellsUsesFormulaParser:
    """Verify extractor uses formula_parser instead of local parsing."""

    def test_no_local_extract_refs_function(self):
        """extractor.py should not have _extract_refs_from_formula."""
        import xlens.extractor as mod
        assert not hasattr(mod, "_extract_refs_from_formula"), \
            "extractor.py still has local _extract_refs_from_formula"

    def test_no_local_col_helpers(self):
        """extractor.py should not have _col_to_num or _num_to_col."""
        import xlens.extractor as mod
        assert not hasattr(mod, "_col_to_num"), \
            "extractor.py still has local _col_to_num"
        assert not hasattr(mod, "_num_to_col"), \
            "extractor.py still has local _num_to_col"

    def test_returns_tuple(self):
        """extract_cells should return (cells, context) tuple."""
        import os
        import tempfile

        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = 1
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name
        wb.save(path)
        wb.close()

        try:
            from xlens.extractor import extract_cells
            result = extract_cells(path)
            assert isinstance(result, tuple), "extract_cells should return a tuple"
            assert len(result) == 2, "extract_cells should return (cells, context)"
            cells, context = result
            assert isinstance(cells, dict)
            assert isinstance(context, dict)
        finally:
            os.unlink(path)
