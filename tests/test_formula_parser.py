"""Unit tests for formula_parser module -- TDD RED phase."""


from xlens.formula_parser import (
    RANGE_COLLAPSE_THRESHOLD,
    build_merged_cell_map,
    build_named_range_map,
    col_to_num,
    expand_or_collapse_range,
    extract_references,
    num_to_col,
    resolve_named_ranges,
)


# ------------------------------------------------------------------ #
# col_to_num / num_to_col
# ------------------------------------------------------------------ #
class TestColumnHelpers:
    def test_col_to_num_single_letters(self):
        assert col_to_num("A") == 1
        assert col_to_num("Z") == 26

    def test_col_to_num_multi_letters(self):
        assert col_to_num("AA") == 27
        assert col_to_num("AZ") == 52
        assert col_to_num("BA") == 53

    def test_num_to_col_single_letters(self):
        assert num_to_col(1) == "A"
        assert num_to_col(26) == "Z"

    def test_num_to_col_multi_letters(self):
        assert num_to_col(27) == "AA"
        assert num_to_col(52) == "AZ"
        assert num_to_col(53) == "BA"

    def test_roundtrip(self):
        for n in [1, 10, 26, 27, 100, 702]:
            assert col_to_num(num_to_col(n)) == n


# ------------------------------------------------------------------ #
# extract_references -- basic cell references
# ------------------------------------------------------------------ #
class TestExtractReferencesBasic:
    def test_simple_addition(self):
        refs, names, warnings = extract_references("=A1+B2", "Sheet1")
        assert ("Sheet1", "A1") in refs
        assert ("Sheet1", "B2") in refs
        assert len(names) == 0
        assert len(warnings) == 0

    def test_absolute_refs_stripped(self):
        refs, names, warnings = extract_references("=$B$5+$C$10", "Sheet1")
        assert ("Sheet1", "B5") in refs
        assert ("Sheet1", "C10") in refs

    def test_mixed_absolute_relative(self):
        refs, names, _ = extract_references("=$A1+B$2", "Sheet1")
        assert ("Sheet1", "A1") in refs
        assert ("Sheet1", "B2") in refs


# ------------------------------------------------------------------ #
# extract_references -- cross-sheet refs
# ------------------------------------------------------------------ #
class TestExtractReferencesCrossSheet:
    def test_quoted_sheet(self):
        refs, _, _ = extract_references("=SUM('Pro Forma'!C5:C10)", "Sheet1")
        assert all(s == "Pro Forma" for s, _ in refs)
        # Should include C5 through C10 (6 cells)
        assert len(refs) == 6
        for i in range(5, 11):
            assert ("Pro Forma", f"C{i}") in refs

    def test_unquoted_sheet(self):
        refs, _, _ = extract_references("=Assumptions!B5", "Sheet1")
        assert ("Assumptions", "B5") in refs

    def test_unquoted_sheet_range(self):
        refs, _, _ = extract_references("=Sheet2!C3:C5", "Sheet1")
        assert ("Sheet2", "C3") in refs
        assert ("Sheet2", "C4") in refs
        assert ("Sheet2", "C5") in refs


# ------------------------------------------------------------------ #
# extract_references -- named ranges
# ------------------------------------------------------------------ #
class TestExtractReferencesNamedRanges:
    def test_named_range_detection(self):
        refs, names, _ = extract_references("=AcquisitionPrice*0.05", "Sheet1")
        assert "AcquisitionPrice" in names
        assert len(refs) == 0  # No cell refs, only a named range

    def test_named_range_in_function(self):
        refs, names, _ = extract_references("=SUM(Revenue)", "Sheet1")
        assert "Revenue" in names

    def test_named_range_mixed_with_cells(self):
        refs, names, _ = extract_references("=CapRate+A1", "Sheet1")
        assert "CapRate" in names
        assert ("Sheet1", "A1") in refs


# ------------------------------------------------------------------ #
# extract_references -- range collapse & open-ended ranges
# ------------------------------------------------------------------ #
class TestExtractReferencesRangeHandling:
    def test_column_only_range_collapses_with_warning(self):
        refs, _, warnings = extract_references("=SUM(A:D)", "Sheet1")
        # Should produce a collapsed node, not expand
        assert len(refs) == 1
        assert len(warnings) > 0
        assert any("open-ended" in w.lower() or "column" in w.lower() for w in warnings)

    def test_row_only_range_collapses_with_warning(self):
        refs, _, warnings = extract_references("=SUM(1:10)", "Sheet1")
        assert len(refs) == 1
        assert len(warnings) > 0

    def test_indirect_warning(self):
        refs, _, warnings = extract_references('=INDIRECT("A"&B1)', "Sheet1")
        assert ("Sheet1", "B1") in refs
        assert len(warnings) > 0
        assert any("indirect" in w.lower() or "dynamic" in w.lower() for w in warnings)


# ------------------------------------------------------------------ #
# expand_or_collapse_range
# ------------------------------------------------------------------ #
class TestExpandOrCollapseRange:
    def test_small_range_expands(self):
        result = expand_or_collapse_range("S1", "A1", "A10")
        assert len(result) == 10
        for i in range(1, 11):
            assert ("S1", f"A{i}") in result

    def test_large_range_collapses(self):
        result = expand_or_collapse_range("S1", "A1", "A600")
        assert len(result) == 1
        # Collapsed node should contain the range notation
        item = next(iter(result))
        assert item[0] == "S1"
        assert "A1" in item[1] and "A600" in item[1]

    def test_threshold_boundary_expands(self):
        """Range of exactly RANGE_COLLAPSE_THRESHOLD cells should expand."""
        result = expand_or_collapse_range("S1", "A1", f"A{RANGE_COLLAPSE_THRESHOLD}")
        assert len(result) == RANGE_COLLAPSE_THRESHOLD

    def test_threshold_plus_one_collapses(self):
        """Range of RANGE_COLLAPSE_THRESHOLD+1 cells should collapse."""
        result = expand_or_collapse_range("S1", "A1", f"A{RANGE_COLLAPSE_THRESHOLD + 1}")
        assert len(result) == 1

    def test_multi_column_range(self):
        result = expand_or_collapse_range("S1", "A1", "C3")
        # 3 cols * 3 rows = 9 cells
        assert len(result) == 9
        assert ("S1", "A1") in result
        assert ("S1", "C3") in result
        assert ("S1", "B2") in result


# ------------------------------------------------------------------ #
# build_named_range_map
# ------------------------------------------------------------------ #
class TestBuildNamedRangeMap:
    def test_basic_mapping(self, mock_workbook):
        nr_map = build_named_range_map(mock_workbook)
        assert "AcquisitionPrice" in nr_map
        assert ("Assumptions", "B5") in nr_map["AcquisitionPrice"]

    def test_filters_xlnm_prefix(self, mock_workbook):
        nr_map = build_named_range_map(mock_workbook)
        assert "_xlnm.Print_Area" not in nr_map
        assert "_xlnm._FilterDatabase" not in nr_map
        assert "Print_Area" not in nr_map

    def test_strips_dollar_signs(self, mock_workbook):
        nr_map = build_named_range_map(mock_workbook)
        # Coordinates should have $ signs stripped
        for _name, destinations in nr_map.items():
            for _sheet, coord in destinations:
                assert "$" not in coord

    def test_multiple_destinations(self, mock_workbook):
        nr_map = build_named_range_map(mock_workbook)
        assert "MultiRange" in nr_map
        assert len(nr_map["MultiRange"]) == 3

    def test_scoped_name_included(self, mock_workbook):
        nr_map = build_named_range_map(mock_workbook)
        assert "ScopedName" in nr_map


# ------------------------------------------------------------------ #
# resolve_named_ranges
# ------------------------------------------------------------------ #
class TestResolveNamedRanges:
    def test_resolve_single_name(self):
        nr_map = {"CapRate": [("Assumptions", "C10")]}
        result = resolve_named_ranges({"CapRate"}, nr_map)
        assert ("Assumptions", "C10") in result

    def test_resolve_range_destination(self):
        nr_map = {"DataRange": [("Sheet1", "A1:A5")]}
        result = resolve_named_ranges({"DataRange"}, nr_map)
        # Should expand A1:A5 into 5 cells
        assert len(result) == 5
        for i in range(1, 6):
            assert ("Sheet1", f"A{i}") in result

    def test_unknown_name_ignored(self):
        nr_map = {"Known": [("S1", "A1")]}
        result = resolve_named_ranges({"Unknown"}, nr_map)
        assert len(result) == 0

    def test_multiple_names(self):
        nr_map = {
            "Price": [("S1", "A1")],
            "Rate": [("S1", "B2")],
        }
        result = resolve_named_ranges({"Price", "Rate"}, nr_map)
        assert ("S1", "A1") in result
        assert ("S1", "B2") in result


# ------------------------------------------------------------------ #
# build_merged_cell_map
# ------------------------------------------------------------------ #
class TestBuildMergedCellMap:
    def test_vertical_merge(self, mock_worksheet):
        mc_map = build_merged_cell_map(mock_worksheet)
        # A1:A3 merge: A2 and A3 should map to A1 anchor
        sheet = mock_worksheet.title
        assert mc_map[sheet][(2, 1)] == (1, 1)  # row 2, col 1 -> row 1, col 1
        assert mc_map[sheet][(3, 1)] == (1, 1)  # row 3, col 1 -> row 1, col 1

    def test_horizontal_merge(self, mock_worksheet):
        mc_map = build_merged_cell_map(mock_worksheet)
        sheet = mock_worksheet.title
        # B5:D5 merge: C5 and D5 should map to B5 anchor
        assert mc_map[sheet][(5, 3)] == (5, 2)  # row 5, col 3 -> row 5, col 2
        assert mc_map[sheet][(5, 4)] == (5, 2)  # row 5, col 4 -> row 5, col 2

    def test_anchor_not_in_map(self, mock_worksheet):
        mc_map = build_merged_cell_map(mock_worksheet)
        sheet = mock_worksheet.title
        # Anchor (1,1) should NOT be in the map -- only non-anchors are redirected
        assert (1, 1) not in mc_map[sheet]
        assert (5, 2) not in mc_map[sheet]


# ------------------------------------------------------------------ #
# RANGE_COLLAPSE_THRESHOLD constant
# ------------------------------------------------------------------ #
class TestConstants:
    def test_threshold_value(self):
        assert RANGE_COLLAPSE_THRESHOLD == 500
