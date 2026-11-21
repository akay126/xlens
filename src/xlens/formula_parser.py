"""Consolidated formula parsing, reference extraction, and range handling.

Replaces duplicated regex-based parsing in extractor.py and graph_builder.py
with openpyxl Tokenizer-based extraction. Handles named ranges, merged cells,
absolute reference stripping, and range collapse.

Public API:
    extract_references(formula, current_sheet) -> (cell_refs, named_ranges, warnings)
    build_named_range_map(workbook) -> dict[str, list[tuple[str, str]]]
    resolve_named_ranges(names, nr_map, current_sheet=None) -> set
    build_merged_cell_map(worksheet) -> dict[str, dict[tuple, tuple]]
    expand_or_collapse_range(sheet, start_ref, end_ref) -> set
    col_to_num(col) -> int
    num_to_col(n) -> str
    RANGE_COLLAPSE_THRESHOLD: int
"""

from __future__ import annotations

import re

from openpyxl.formula import Tokenizer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RANGE_COLLAPSE_THRESHOLD = 500

# Pattern matching a cell reference: 1-3 uppercase letters followed by digits.
# Allows optional $ for absolute references (which get stripped).
_CELL_REF_RE = re.compile(r"^\$?([A-Z]{1,3})\$?(\d+)$")

# Column-only range like A:D
_COL_RANGE_RE = re.compile(r"^\$?([A-Z]{1,3}):\$?([A-Z]{1,3})$")

# Row-only range like 1:10
_ROW_RANGE_RE = re.compile(r"^(\d+):(\d+)$")

# Standard range like A1:B10 (with optional $ signs)
_RANGE_RE = re.compile(
    r"^\$?([A-Z]{1,3})\$?(\d+):\$?([A-Z]{1,3})\$?(\d+)$"
)

# Dynamic formula functions that prevent full static resolution
_DYNAMIC_FUNCS = {"INDIRECT", "OFFSET"}


# ---------------------------------------------------------------------------
# Column helpers
# ---------------------------------------------------------------------------

def col_to_num(col: str) -> int:
    """Convert column letter(s) to number. A=1, Z=26, AA=27."""
    result = 0
    for c in col.upper():
        result = result * 26 + (ord(c) - ord("A") + 1)
    return result


def num_to_col(n: int) -> str:
    """Convert number to column letter(s). 1=A, 26=Z, 27=AA."""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


# ---------------------------------------------------------------------------
# Range expansion / collapse
# ---------------------------------------------------------------------------

def expand_or_collapse_range(sheet: str, start_ref: str, end_ref: str) -> set:
    """Expand a range into individual cell tuples, or collapse if too large.

    Args:
        sheet: Sheet name.
        start_ref: Start cell e.g. "A1" (no $ signs).
        end_ref: End cell e.g. "A600" (no $ signs).

    Returns:
        Set of (sheet, coord) tuples. If the range exceeds
        RANGE_COLLAPSE_THRESHOLD cells, returns a single collapsed
        node {(sheet, "start_ref:end_ref")}.
    """
    m1 = re.match(r"([A-Z]{1,3})(\d+)", start_ref)
    m2 = re.match(r"([A-Z]{1,3})(\d+)", end_ref)
    if not m1 or not m2:
        return set()

    col_start = col_to_num(m1.group(1))
    row_start = int(m1.group(2))
    col_end = col_to_num(m2.group(1))
    row_end = int(m2.group(2))

    num_cols = abs(col_end - col_start) + 1
    num_rows = abs(row_end - row_start) + 1
    cell_count = num_cols * num_rows

    if cell_count > RANGE_COLLAPSE_THRESHOLD:
        return {(sheet, f"{start_ref}:{end_ref}")}

    refs = set()
    for col_num in range(min(col_start, col_end), max(col_start, col_end) + 1):
        for row_num in range(min(row_start, row_end), max(row_start, row_end) + 1):
            refs.add((sheet, f"{num_to_col(col_num)}{row_num}"))
    return refs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_dollars(ref: str) -> str:
    """Remove all $ signs from a cell/range reference."""
    return ref.replace("$", "")


def _split_sheet_ref(value: str, current_sheet: str) -> tuple[str, str]:
    """Split a token value like "'Pro Forma'!C5" or "Sheet1!A1" into (sheet, ref).

    If no sheet prefix, uses *current_sheet*.
    """
    if "!" in value:
        sheet_part, ref_part = value.split("!", 1)
        # Strip surrounding quotes from sheet name
        sheet_part = sheet_part.strip("'")
        return sheet_part, _strip_dollars(ref_part)
    return current_sheet, _strip_dollars(value)


# ---------------------------------------------------------------------------
# extract_references  (main entry point)
# ---------------------------------------------------------------------------

def extract_references(
    formula: str, current_sheet: str
) -> tuple[set, set, list]:
    """Extract cell references, named range names, and warnings from a formula.

    Uses openpyxl Tokenizer for robust token-level parsing.

    Args:
        formula: Excel formula string (with leading '=').
        current_sheet: Name of the sheet containing this formula.

    Returns:
        (cell_refs, named_range_names, warnings) where:
        - cell_refs: set of (sheet, coord) tuples
        - named_range_names: set of str (unresolved named range identifiers)
        - warnings: list of str (dynamic refs, collapsed ranges, etc.)
    """
    cell_refs: set[tuple[str, str]] = set()
    named_ranges: set[str] = set()
    warnings: list[str] = []

    # Track whether we are inside a dynamic function
    has_dynamic = False
    func_stack: list[str] = []

    tok = Tokenizer(formula)

    for token in tok.items:
        # Track function calls to detect INDIRECT/OFFSET
        if token.type == "FUNC" and token.subtype == "OPEN":
            func_name = token.value.rstrip("(").upper()
            func_stack.append(func_name)
            if func_name in _DYNAMIC_FUNCS:
                has_dynamic = True
        elif token.type == "FUNC" and token.subtype == "CLOSE":
            if func_stack:
                func_stack.pop()

        # Only process OPERAND tokens of subtype RANGE
        if token.type != "OPERAND" or token.subtype != "RANGE":
            continue

        raw = token.value
        sheet, ref = _split_sheet_ref(raw, current_sheet)

        # ----- Column-only range (e.g. A:D) -----
        m_col = _COL_RANGE_RE.match(ref)
        if m_col:
            collapsed = f"{m_col.group(1)}:{m_col.group(2)}"
            cell_refs.add((sheet, collapsed))
            warnings.append(
                f"Open-ended column range {raw} collapsed to single node"
            )
            continue

        # ----- Row-only range (e.g. 1:10) -----
        m_row = _ROW_RANGE_RE.match(ref)
        if m_row:
            collapsed = f"{m_row.group(1)}:{m_row.group(2)}"
            cell_refs.add((sheet, collapsed))
            warnings.append(
                f"Open-ended row range {raw} collapsed to single node"
            )
            continue

        # ----- Standard range (e.g. A1:B10) -----
        m_range = _RANGE_RE.match(ref)
        if m_range:
            start = f"{m_range.group(1)}{m_range.group(2)}"
            end = f"{m_range.group(3)}{m_range.group(4)}"
            cell_refs.update(expand_or_collapse_range(sheet, start, end))
            continue

        # ----- Single cell reference -----
        m_cell = _CELL_REF_RE.match(ref)
        if m_cell:
            coord = f"{m_cell.group(1)}{m_cell.group(2)}"
            cell_refs.add((sheet, coord))
            continue

        # ----- If none of the above matched, it's likely a named range -----
        # Named ranges are identifiers that don't match cell patterns
        if re.match(r"^[A-Za-z_]\w*$", ref) and not ref.upper().startswith("_XLNM"):
            named_ranges.add(ref)

    # Add warning for dynamic functions
    if has_dynamic:
        warnings.append(
            "Formula contains dynamic reference (INDIRECT/OFFSET); "
            "only static parts resolved"
        )

    return cell_refs, named_ranges, warnings


# ---------------------------------------------------------------------------
# Named range map
# ---------------------------------------------------------------------------

def build_named_range_map(
    workbook,
) -> dict[str, list[tuple[str, str]]]:
    """Build a map of named ranges from workbook defined names.

    Args:
        workbook: openpyxl Workbook (or mock with .defined_names).

    Returns:
        Dict mapping name -> list of (sheet, coord) tuples.
        Filters out _xlnm. prefixed internal names.
        Strips $ signs from all coordinates.
    """
    nr_map: dict[str, list[tuple[str, str]]] = {}

    for item in workbook.defined_names:
        # openpyxl iteration yields strings (names) for real workbooks,
        # but mock objects may yield DefinedName-like objects directly.
        if isinstance(item, str):
            name = item
            # Filter out Excel internal names
            if name.startswith("_xlnm."):
                continue
            try:
                defn = workbook.defined_names[name]
            except (KeyError, TypeError):
                continue
        else:
            # Mock or DefinedName-like object with .name and .destinations
            defn = item
            name = defn.name
            if name.startswith("_xlnm."):
                continue

        destinations = []
        try:
            for sheet_title, coord in defn.destinations:
                clean_coord = _strip_dollars(coord)
                destinations.append((sheet_title, clean_coord))
        except Exception:
            continue

        if destinations:
            nr_map[name] = destinations

    return nr_map


# ---------------------------------------------------------------------------
# Resolve named ranges
# ---------------------------------------------------------------------------

def resolve_named_ranges(
    names: set[str],
    nr_map: dict[str, list[tuple[str, str]]],
    current_sheet: str | None = None,
) -> set[tuple[str, str]]:
    """Resolve named range names to (sheet, coord) tuples.

    Expands ranges found in the named range destinations.

    Args:
        names: Set of named range identifiers to resolve.
        nr_map: Map from build_named_range_map.
        current_sheet: Optional fallback sheet for unqualified names.

    Returns:
        Set of (sheet, coord) tuples.
    """
    resolved: set[tuple[str, str]] = set()

    for name in names:
        if name not in nr_map:
            continue
        for sheet, coord in nr_map[name]:
            # Check if coord is a range (contains ':')
            m_range = _RANGE_RE.match(coord)
            if m_range:
                start = f"{m_range.group(1)}{m_range.group(2)}"
                end = f"{m_range.group(3)}{m_range.group(4)}"
                resolved.update(expand_or_collapse_range(sheet, start, end))
            else:
                resolved.add((sheet, coord))

    return resolved


# ---------------------------------------------------------------------------
# Merged cell map
# ---------------------------------------------------------------------------

def build_merged_cell_map(
    worksheet,
) -> dict[str, dict[tuple[int, int], tuple[int, int]]]:
    """Build a redirect map for merged cells.

    Maps every non-anchor cell in a merged range to the anchor (top-left) cell.

    Args:
        worksheet: openpyxl Worksheet (or mock with .title and .merged_cells.ranges).

    Returns:
        Dict keyed by sheet name, value is dict mapping (row, col) -> (anchor_row, anchor_col).
        Only non-anchor cells appear as keys.
    """
    sheet_name = worksheet.title
    redirect: dict[tuple[int, int], tuple[int, int]] = {}

    for merged_range in worksheet.merged_cells.ranges:
        anchor = (merged_range.min_row, merged_range.min_col)
        for row in range(merged_range.min_row, merged_range.max_row + 1):
            for col in range(merged_range.min_col, merged_range.max_col + 1):
                cell = (row, col)
                if cell != anchor:
                    redirect[cell] = anchor

    return {sheet_name: redirect}
