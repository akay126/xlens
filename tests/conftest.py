"""Shared pytest fixtures for formula parser and graph builder tests."""

from unittest.mock import MagicMock

import pytest

from tests.fixtures.build_models import build_all


class MockDefinedName:
    """Mock of openpyxl DefinedName for testing build_named_range_map."""

    def __init__(self, name, destinations, local_sheet_id=None):
        self.name = name
        self._destinations = destinations
        self.localSheetId = local_sheet_id

    @property
    def destinations(self):
        return iter(self._destinations)


class MockDefinedNameList:
    """Mock of openpyxl DefinedNameList that supports iteration."""

    def __init__(self, names):
        self._names = names

    def __iter__(self):
        return iter(self._names)


class MockMergedCellRange:
    """Mock of openpyxl MergedCellRange."""

    def __init__(self, min_row, min_col, max_row, max_col):
        self.min_row = min_row
        self.min_col = min_col
        self.max_row = max_row
        self.max_col = max_col


class MockMergedCells:
    """Mock of worksheet.merged_cells with .ranges property."""

    def __init__(self, ranges):
        self._ranges = ranges

    @property
    def ranges(self):
        return self._ranges


@pytest.fixture
def mock_workbook():
    """Mock openpyxl Workbook with defined_names."""
    wb = MagicMock()
    wb.defined_names = MockDefinedNameList([
        MockDefinedName("AcquisitionPrice", [("Assumptions", "$B$5")]),
        MockDefinedName("CapRate", [("Assumptions", "$C$10")]),
        MockDefinedName("_xlnm.Print_Area", [("Sheet1", "$A$1:$Z$100")]),
        MockDefinedName("_xlnm._FilterDatabase", [("Data", "$A$1:$D$50")]),
        MockDefinedName("MultiRange", [
            ("Sheet1", "$A$1"),
            ("Sheet1", "$A$2"),
            ("Sheet1", "$A$3"),
        ]),
        MockDefinedName("ScopedName", [("Sheet2", "$D$4")], local_sheet_id=0),
    ])
    return wb


@pytest.fixture
def mock_worksheet():
    """Mock openpyxl Worksheet with merged_cells."""
    ws = MagicMock()
    ws.title = "Sheet1"
    ws.merged_cells = MockMergedCells([
        MockMergedCellRange(min_row=1, min_col=1, max_row=3, max_col=1),  # A1:A3
        MockMergedCellRange(min_row=5, min_col=2, max_row=5, max_col=4),  # B5:D5
    ])
    return ws




@pytest.fixture(scope="session")
def models(tmp_path_factory):
    """Paths to every generated workbook: sample, scenarios, circular, hostile, big."""
    return build_all(tmp_path_factory.mktemp("models"))
