"""Cell extraction and classification from Excel workbooks."""

import re

import openpyxl

from xlens.formula_parser import (
    build_merged_cell_map,
    build_named_range_map,
    col_to_num,
    extract_references,
    num_to_col,
    resolve_named_ranges,
)
from xlens.sheet_roles import classify_sheets


def extract_cells(filepath: str) -> tuple:
    """Load workbook and extract all cells with classification.

    Returns (cells, context) where:
        cells: dict keyed by (sheet_name, cell_ref) with:
            sheet, cell_ref, row, col, raw_value, formula, cached_value,
            data_type, classification, label (row label from col A)
        context: dict with:
            named_range_map: dict of named range -> [(sheet, coord), ...]
            merged_cell_maps: dict of sheet_name -> {(row, col) -> (anchor_row, anchor_col)}
            parser_warnings: list of warning strings
    """
    wb_formulas = openpyxl.load_workbook(filepath, data_only=False)
    wb_values = openpyxl.load_workbook(filepath, data_only=True)

    cells = {}

    # Build named range map from workbook
    nr_map = build_named_range_map(wb_formulas)

    # Build merged cell maps per sheet
    merged_cell_maps = {}
    for sheet_name in wb_formulas.sheetnames:
        ws_f = wb_formulas[sheet_name]
        sheet_merged = build_merged_cell_map(ws_f)
        merged_cell_maps.update(sheet_merged)

    all_warnings = []

    # First pass: collect all cells
    for sheet_name in wb_formulas.sheetnames:
        ws_f = wb_formulas[sheet_name]
        ws_v = wb_values[sheet_name]

        for row in ws_f.iter_rows(min_row=1, max_row=ws_f.max_row,
                                   max_col=ws_f.max_column):
            for cell in row:
                if cell.value is None:
                    continue

                coord = cell.coordinate
                cached = ws_v[coord].value

                raw = cell.value
                formula = None
                if isinstance(raw, str) and raw.startswith("="):
                    formula = raw
                    raw = None

                # Get row label (column A value for this row)
                label_cell = ws_f.cell(row=cell.row, column=1)
                row_label = str(label_cell.value) if label_cell.value else ""

                cells[(sheet_name, coord)] = {
                    "sheet": sheet_name,
                    "cell_ref": coord,
                    "row": cell.row,
                    "col": cell.column,
                    "raw_value": raw,
                    "formula": formula,
                    "cached_value": cached,
                    "data_type": cell.data_type,
                    "row_label": row_label,
                    "classification": None,
                }

    # Collect all cells referenced by formulas (to identify deal_input)
    referenced_cells = set()
    for _key, cell_data in cells.items():
        if cell_data["formula"]:
            cell_refs, named_refs, warnings = extract_references(
                cell_data["formula"], cell_data["sheet"]
            )
            all_warnings.extend(warnings)

            # Resolve named ranges to cell refs
            if named_refs and nr_map:
                resolved = resolve_named_ranges(named_refs, nr_map, cell_data["sheet"])
                cell_refs = cell_refs | resolved

            # Apply merged cell redirect
            sheet_merged = merged_cell_maps.get(cell_data["sheet"], {})
            redirected_refs = set()
            for ref_sheet, ref_coord in cell_refs:
                ref_merged = merged_cell_maps.get(ref_sheet, {})
                # Parse coord to (row, col) for redirect lookup
                m = re.match(r"([A-Z]{1,3})(\d+)", ref_coord)
                if m and ref_merged:
                    ref_col = col_to_num(m.group(1))
                    ref_row = int(m.group(2))
                    anchor = ref_merged.get((ref_row, ref_col))
                    if anchor:
                        # Redirect to anchor cell
                        anchor_coord = f"{num_to_col(anchor[1])}{anchor[0]}"
                        redirected_refs.add((ref_sheet, anchor_coord))
                    else:
                        redirected_refs.add((ref_sheet, ref_coord))
                else:
                    redirected_refs.add((ref_sheet, ref_coord))

            referenced_cells.update(redirected_refs)

    # Second pass: work out sheet roles, then classify
    by_sheet = {name: [] for name in wb_formulas.sheetnames}  # workbook order
    for (sheet, _), cell_data in cells.items():
        by_sheet.setdefault(sheet, []).append(cell_data)
    sheet_roles = classify_sheets(by_sheet)
    for key, cell_data in cells.items():
        cell_data["sheet_role"] = sheet_roles.get(key[0], "calc")
        cell_data["classification"] = _classify_cell(
            cell_data, key, referenced_cells
        )

    wb_formulas.close()
    wb_values.close()

    context = {
        "named_range_map": nr_map,
        "merged_cell_maps": merged_cell_maps,
        "parser_warnings": all_warnings,
        "sheet_roles": sheet_roles,
    }

    return cells, context


_RATE_KEYWORDS = re.compile(
    r"rate|growth|escalation|vacancy|cap|fee|%|ocaf|bump|reserve|mip|ltv|split|share",
    re.IGNORECASE,
)


def _classify_cell(cell_data: dict, key: tuple, referenced_cells: set) -> str:
    """Classify a cell based on its properties and context."""
    sheet, coord = key
    row = cell_data["row"]
    col = cell_data["col"]
    formula = cell_data["formula"]
    raw = cell_data["raw_value"]
    row_label = cell_data["row_label"]

    # Derived: has formula
    if formula:
        return "derived"

    # Metadata: row 1 or column A strings (headers/titles/section labels)
    if isinstance(raw, str):
        if row <= 2 or col == 1:
            return "metadata"
        # String in column C+ on an input sheet = source note
        if cell_data.get("sheet_role") == "input" and col >= 3:
            return "metadata"
        return "label"

    # From here, raw is numeric (int or float) or date-like
    if not isinstance(raw, (int, float)):
        # Dates, booleans, etc.
        if col == 1 or row <= 2:
            return "metadata"
        return "label"

    # Numeric values
    if cell_data.get("sheet_role") == "input":
        if (sheet, coord) in referenced_cells:
            # Check if it's a structural assumption (rate/percentage)
            is_rate = (isinstance(raw, float) and 0 < raw < 1) or bool(
                _RATE_KEYWORDS.search(row_label)
            )
            if is_rate:
                return "structural_assumption"
            return "deal_input"
        # Unreferenced numeric on an input sheet
        return "deal_input"
    else:
        # Calc sheet: hardcoded numeric
        if row <= 3 or col == 1:
            return "metadata"
        return "hardcoded_in_cashflow"
