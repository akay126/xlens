"""Classify sheets as 'input' (assumptions) or 'calc' without relying on sheet names alone."""
import re

_INPUT_NAME = re.compile(r"assum|input|driver|param|setup|key\s*terms", re.IGNORECASE)
_INPUT_FORMULA_RATIO = 0.25


def classify_sheets(sheet_cells: dict) -> dict:
    """sheet_cells: {sheet: [cell_data, ...]} -> {sheet: 'input' | 'calc'}.

    A sheet is an input sheet when its name looks like one, or when fewer than 25%
    of its numeric/formula cells are formulas. Everything else is a calc sheet.
    """
    roles = {}
    for sheet, cells in sheet_cells.items():
        if _INPUT_NAME.search(sheet):
            roles[sheet] = "input"
            continue
        formulas = sum(1 for c in cells if c.get("formula"))
        numbers = sum(1 for c in cells if not c.get("formula") and isinstance(c.get("raw_value"), (int, float)))
        total = formulas + numbers
        roles[sheet] = "input" if total and formulas / total < _INPUT_FORMULA_RATIO else "calc"
    return roles
