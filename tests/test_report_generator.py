"""Tests for the report_generator template system and HTML structure."""

import json
import os
import tempfile

import pytest

from xlens.report_generator import generate_report

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_results():
    """Minimal results dict accepted by generate_report."""
    return {
        "metadata": {
            "model_name": "Test Model",
            "property_name": "123 Main St",
            "date_analyzed": "2026-01-01",
            "sheet_count": 2,
        },
        "cells_summary": {
            "total": 100,
            "formula_count": 40,
            "classification_dist": {"derived": 40, "deal_input": 20, "label": 40},
        },
        "assumptions": [
            {
                "name": "Cap Rate",
                "cell_ref": "B5",
                "value": 0.065,
                "category": "Acquisition",
                "deal_specific": True,
                "downstream_count": 8,
            }
        ],
        "hardcodes": [
            {
                "sheet": "Pro Forma",
                "cell_ref": "C10",
                "value": 1000,
                "severity": "warning",
                "label_context": "Revenue",
                "source_type": "constant",
                "recommendation": "Link to assumptions",
            }
        ],
        "kpis": [
            {
                "name": "IRR",
                "cell_ref": "D20",
                "formatted_value": "12.5%",
                "chain_depth": 5,
                "upstream_count": 30,
                "top_assumptions": [("Cap Rate", 8)],
            }
        ],
        "flow_blocks": [
            {
                "name": "Revenue",
                "description": "Rental income",
                "cell_count": 10,
                "formula_count": 5,
                "connects_to": ["Expenses"],
                "key_formulas": [],
                "driving_assumptions": [],
            }
        ],
        "graph_stats": {
            "total_nodes": 100,
            "total_edges": 150,
            "root_count": 10,
            "hub_nodes": [],
            "root_nodes": [],
            "terminal_nodes": [],
            "has_circular_refs": False,
            "parser_warnings": [],
        },
        "cells": {
            ("Sheet1", "A1"): {
                "cell_ref": "A1",
                "row": 1,
                "col": 1,
                "formula": None,
                "raw_value": "Hello",
                "cached_value": "Hello",
                "classification": "label",
                "sheet": "Sheet1",
            }
        },
        "pro_forma": {},
        "complexity": {
            "score": 45,
            "grade": "C",
            "metrics": {},
            "critical_path": [],
            "bottleneck_cells": [],
        },
        "graph_json": '{"nodes":[],"links":[]}',
    }


# ---------------------------------------------------------------------------
# Template infrastructure tests
# ---------------------------------------------------------------------------


class TestTemplateLoading:
    """Tests for template file loading."""

    def test_load_template_base_html(self):
        from xlens.report_generator import _load_template

        content = _load_template("base.html")
        assert "%{css}" in content or "${css}" in content
        assert "%{body}" in content or "${body}" in content

    def test_load_template_report_css(self):
        from xlens.report_generator import _load_template

        content = _load_template("report.css")
        assert ":root" in content

    def test_html_template_substitution(self):
        from xlens.report_generator import HtmlTemplate

        tpl = HtmlTemplate("Hello %{name}, your score is %{score}.")
        result = tpl.substitute(name="Alice", score="95")
        assert result == "Hello Alice, your score is 95."

    def test_html_template_does_not_conflict_with_css(self):
        """CSS curly braces must not conflict with %{var} syntax."""
        from xlens.report_generator import HtmlTemplate

        # CSS with regular curly braces should be fine
        tpl = HtmlTemplate("<style>%{css}</style>")
        css = "body { color: red; }"
        result = tpl.substitute(css=css)
        assert "body { color: red; }" in result


class TestGenerateReport:
    """Tests for the generate_report function."""

    def test_produces_valid_html(self, mock_results):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            output_path = f.name
        try:
            generate_report(mock_results, output_path)
            with open(output_path, "r") as f:
                html = f.read()
            assert "<!DOCTYPE html>" in html
            assert "<html" in html
            assert "<head>" in html
            assert "<body>" in html
        finally:
            os.unlink(output_path)

    def test_contains_inlined_css(self, mock_results):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            output_path = f.name
        try:
            generate_report(mock_results, output_path)
            with open(output_path, "r") as f:
                html = f.read()
            assert "<style>" in html
            assert ":root" in html
            assert "--bg:" in html
        finally:
            os.unlink(output_path)

    def test_self_contained_no_external_links(self, mock_results):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            output_path = f.name
        try:
            generate_report(mock_results, output_path)
            with open(output_path, "r") as f:
                html = f.read()
            # Should not have <link rel="stylesheet"
            assert '<link rel="stylesheet"' not in html
        finally:
            os.unlink(output_path)

    def test_api_signature_unchanged(self, mock_results):
        """generate_report(results, output_path) still works."""
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            output_path = f.name
        try:
            # Should not raise
            generate_report(mock_results, output_path)
            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) > 0
        finally:
            os.unlink(output_path)

    def test_title_from_metadata(self, mock_results):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            output_path = f.name
        try:
            generate_report(mock_results, output_path)
            with open(output_path, "r") as f:
                html = f.read()
            assert "<title>Test Model</title>" in html
        finally:
            os.unlink(output_path)

    def test_css_not_from_old_variable(self):
        """The old _CSS variable should no longer exist."""
        import xlens.report_generator as mod
        assert not hasattr(mod, "_CSS"), "_CSS variable should be removed from report_generator"


# ---------------------------------------------------------------------------
# Section structure tests (details/summary, thead/tbody)
# ---------------------------------------------------------------------------


@pytest.fixture
def generated_html(mock_results):
    """Generate HTML once for structure tests."""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        output_path = f.name
    generate_report(mock_results, output_path)
    with open(output_path, "r") as f:
        html = f.read()
    os.unlink(output_path)
    return html


class TestSectionStructure:
    """Tests for details/summary and thead/tbody markup."""

    def test_contains_details_elements(self, generated_html):
        assert "<details" in generated_html

    def test_contains_summary_elements(self, generated_html):
        assert "<summary>" in generated_html

    def test_summary_section_not_wrapped_in_details(self, generated_html):
        """The Executive Summary section should NOT be inside a details element."""
        # Find the summary section
        idx = generated_html.find('id="summary"')
        assert idx > 0
        # Get a window around the section start
        section_start = generated_html.rfind("<section", 0, idx)
        before_section = generated_html[max(0, section_start - 50):section_start]
        # Should not have <details directly before the section
        assert "<details" not in before_section or "</details>" in before_section

    def test_nav_not_wrapped_in_details(self, generated_html):
        """Navigation should NOT be inside a details element."""
        nav_idx = generated_html.find('class="nav"')
        assert nav_idx > 0
        before_nav = generated_html[max(0, nav_idx - 100):nav_idx]
        assert "<details" not in before_nav

    def test_flow_section_has_details(self, generated_html):
        idx = generated_html.find('id="flow"')
        assert idx > 0
        section_chunk = generated_html[idx:idx + 200]
        assert "<details open>" in section_chunk
        assert "<summary>" in section_chunk

    def test_kpi_section_has_details(self, generated_html):
        idx = generated_html.find('id="kpis"')
        assert idx > 0
        section_chunk = generated_html[idx:idx + 200]
        assert "<details open>" in section_chunk

    def test_tables_contain_thead(self, generated_html):
        assert "<thead>" in generated_html

    def test_tables_contain_tbody(self, generated_html):
        assert "<tbody>" in generated_html

    def test_sortable_th_class(self, generated_html):
        """Sortable tables should have th elements with class='sortable'."""
        assert 'class="sortable"' in generated_html

    def test_toggle_all_button_exists(self, generated_html):
        assert 'id="toggle-all"' in generated_html
        assert "Collapse All" in generated_html

    def test_assumptions_section_has_details(self, generated_html):
        idx = generated_html.find('id="assumptions"')
        assert idx > 0
        section_chunk = generated_html[idx:idx + 200]
        assert "<details>" in section_chunk

    def test_hardcodes_section_has_details(self, generated_html):
        idx = generated_html.find('id="hardcodes"')
        assert idx > 0
        section_chunk = generated_html[idx:idx + 200]
        assert "<details>" in section_chunk

    def test_complexity_section_has_details_open(self, generated_html):
        idx = generated_html.find('id="complexity"')
        assert idx > 0
        section_chunk = generated_html[idx:idx + 300]
        assert "<details open>" in section_chunk

    def test_cells_section_has_details(self, generated_html):
        idx = generated_html.find('id="cells"')
        assert idx > 0
        section_chunk = generated_html[idx:idx + 200]
        assert "<details>" in section_chunk


# ---------------------------------------------------------------------------
# Interactive features and print CSS tests (02-02)
# ---------------------------------------------------------------------------


class TestInteractiveFeatures:
    """Tests for sort.js, collapse.js, and print CSS."""

    def test_sort_js_inlined(self, generated_html):
        """Sort JS content should be present in report output."""
        assert "th.sortable" in generated_html
        assert "data-sort-dir" in generated_html

    def test_collapse_js_inlined(self, generated_html):
        """Collapse JS content should be present in report output."""
        assert "toggle-all" in generated_html
        assert "Expand All" in generated_html or "Collapse All" in generated_html

    def test_print_css_present(self, generated_html):
        """Output CSS should contain @media print block."""
        assert "@media print" in generated_html

    def test_print_header_present(self, generated_html):
        """Print header div should be in the output."""
        assert 'class="print-header"' in generated_html
        assert "Generated by xlens" in generated_html

    def test_print_footer_present(self, generated_html):
        """Print footer div should be in the output."""
        assert 'class="print-footer"' in generated_html
        assert "Report generated" in generated_html

    def test_sort_indicator_css(self, generated_html):
        """Sort indicator CSS with th.sortable::after should be present."""
        assert "th.sortable::after" in generated_html
        assert "th.sort-asc::after" in generated_html
        assert "th.sort-desc::after" in generated_html


# ---------------------------------------------------------------------------
# Row map + Trace dependency explorer
# ---------------------------------------------------------------------------


class TestDependencyExplorer:
    """The explorer mounts in the dependencies section and gets KPI refs as JSON."""

    def _render(self, results):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            output_path = f.name
        try:
            generate_report(results, output_path)
            with open(output_path, "r", encoding="utf-8") as f:
                return f.read()
        finally:
            os.unlink(output_path)

    def _kpi_json(self, html):
        start = html.index('<script type="application/json" id="xe-kpis">') + len(
            '<script type="application/json" id="xe-kpis">'
        )
        end = html.index("</script>", start)
        return json.loads(html[start:end])

    def test_explorer_mount_and_script_present(self, generated_html):
        assert 'id="xe-root"' in generated_html
        assert "MAP_ROW_LIMIT" in generated_html  # explorer.js is inlined

    def test_kpi_refs_embedded(self, mock_results):
        html = self._render(mock_results)
        mock_results["kpis"][0]["cell_ref"] = "Exit & Returns!D20"  # real KPIs carry the node id
        html = self._render(mock_results)
        assert self._kpi_json(html) == [{"cell": "Exit & Returns!D20", "name": "IRR"}]

    def test_kpi_name_cannot_close_script_tag(self, mock_results):
        mock_results["kpis"][0]["name"] = "</script><script>alert(1)</script>"
        html = self._render(mock_results)
        assert "</script><script>alert(1)" not in html
        assert self._kpi_json(html)[0]["name"] == "</script><script>alert(1)</script>"

    def test_graph_json_cannot_break_out_of_script(self, mock_results):
        evil = '</SCRIPT ><img src=x onerror=alert(1)><!--<script>'
        mock_results["graph_json"] = json.dumps({
            "nodes": [{"id": "S!A1", "sheet": "S", "cell_ref": "A1", "row_label": evil,
                       "formula": "", "value": "1", "classification": "deal_input",
                       "in_degree": 0, "out_degree": 0}],
            "links": [],
        })
        html = self._render(mock_results)
        line = next(ln for ln in html.splitlines() if ln.startswith("const graphData = "))
        assert "<" not in line[len("const graphData = "):]
        data = json.loads(line[len("const graphData = "):].rstrip(";"))
        assert data["nodes"][0]["row_label"] == evil


class TestNo3D:
    def test_no_3d_graph(self, generated_html):
        assert "ForceGraph3D" not in generated_html and "3d-graph" not in generated_html

    def test_main_schedule_not_hardcoded(self, models, tmp_path):
        from xlens.analysis import run_pipeline
        from xlens.report_generator import generate_report
        out = tmp_path / "r.html"
        generate_report(run_pipeline(str(models["sample"])).results, str(out))
        assert "Main schedule: Cash Flow" in out.read_text()

    def test_main_schedule_follows_formula_sheet(self, models, tmp_path):
        from xlens.analysis import run_pipeline
        out = tmp_path / "r.html"
        generate_report(run_pipeline(str(models["scenarios"])).results, str(out))
        assert "Main schedule: Returns" in out.read_text()

    def test_no_calculation_sheet_fallback(self):
        from xlens.report_generator import _build_proforma
        cells = {("Inputs", "A1"): {"sheet": "Inputs", "sheet_role": "input", "row": 1, "col": 1,
                                    "formula": None, "raw_value": 5}}
        assert "No calculation sheet found." in _build_proforma({}, cells)
