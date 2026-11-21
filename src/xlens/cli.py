"""CLI entry point for xlens."""

import argparse
import csv
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from xlens.analysis import AnalysisError, run_pipeline
from xlens.report_generator import generate_report


def cmd_analyze(args):
    """Run the full pipeline on a single Excel model."""
    excel_path = args.file
    if args.output:
        output_path = args.output
    else:
        basename = Path(excel_path).stem
        output_path = f"output/{basename}_report.html"

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    print("Excel Reverse Engineering Pipeline")
    print(f"{'='*50}")
    print(f"Input:  {excel_path}")
    print(f"Output: {output_path}")
    print()

    start = time.time()

    print("Analyzing...", end=" ", flush=True)
    t = time.time()
    try:
        analysis = run_pipeline(excel_path)
    except AnalysisError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)
    results = analysis.results
    cells = analysis.cells
    sheet_names = results["metadata"]["sheet_names"]
    formula_count = results["cells_summary"]["formula_count"]
    assumptions = results["assumptions"]
    hardcodes = results["hardcodes"]
    kpis = results["kpis"]
    flow_blocks = results["flow_blocks"]
    complexity = results["complexity"]
    graph_stats = results["graph_stats"]
    print(f"done ({len(cells)} cells, {graph_stats['total_nodes']} nodes, "
          f"{graph_stats['total_edges']} edges in {time.time()-t:.1f}s)")

    # Step 8: Generate report
    print("Generating HTML report...", end=" ", flush=True)
    t = time.time()
    generate_report(results, output_path)
    report_size = os.path.getsize(output_path)
    print(f"done ({report_size:,} bytes in {time.time()-t:.1f}s)")

    elapsed = time.time() - start
    print()
    print(f"{'='*50}")
    print(f"Pipeline complete in {elapsed:.1f}s")
    print(f"Report: {output_path} ({report_size:,} bytes)")
    print()
    print("Summary:")
    print(f"  Sheets:      {len(sheet_names)} ({', '.join(sheet_names)})")
    print(f"  Cells:       {len(cells)}")
    print(f"  Formulas:    {formula_count}")
    print(f"  Assumptions: {len(assumptions)}")
    print(f"  KPIs:        {len(kpis)}")
    print(f"  Hardcodes:   {len(hardcodes)}")
    print(f"  Flow blocks: {len(flow_blocks)}")
    print(f"  Complexity:  {complexity['score']}/100 (Grade {complexity['grade']})")


def cmd_batch(args):
    """Run the pipeline on all Excel files in a directory."""

    directory = args.directory
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a directory")
        sys.exit(1)

    output_dir = args.output_dir or "output"
    os.makedirs(output_dir, exist_ok=True)

    # Find Excel files
    excel_files = []
    for root, _dirs, filenames in os.walk(directory):
        for fname in filenames:
            if fname.endswith(".xlsx") and not fname.startswith("~"):
                excel_files.append(os.path.join(root, fname))
    excel_files.sort()

    if not excel_files:
        print(f"No .xlsx files found in '{directory}'")
        sys.exit(1)

    print("Batch Analysis Pipeline")
    print(f"{'=' * 60}")
    print(f"Directory: {directory}")
    print(f"Files found: {len(excel_files)}")
    print()

    summaries = []
    errors = []
    for i, excel_path in enumerate(excel_files, 1):
        print(f"[{i}/{len(excel_files)}] {Path(excel_path).name}...", end=" ", flush=True)
        try:
            summary = _analyze_single_model(excel_path, output_dir)
            summaries.append(summary)
            print(
                f"done ({summary['cell_count']} cells, "
                f"{summary['assumption_count']} assumptions, "
                f"{summary['kpi_count']} KPIs, "
                f"{summary['elapsed']}s)"
            )
        except AnalysisError as e:
            errors.append({"file": excel_path, "error": str(e)})
            print(f"FAILED: {e}")
        except Exception as e:
            errors.append({"file": excel_path, "error": str(e)})
            print(f"FAILED: {e}")
            traceback.print_exc()

    if not summaries:
        print("\nNo models were successfully analyzed.")
        sys.exit(1)

    # Generate portfolio outputs
    print()
    print("Generating portfolio outputs...")

    csv_path = os.path.join(output_dir, "portfolio_data.csv")
    _generate_portfolio_csv(summaries, csv_path)
    print(f"  CSV:  {csv_path}")

    html_path = os.path.join(output_dir, "portfolio_summary.html")
    _generate_portfolio_html(summaries, html_path)
    print(f"  HTML: {html_path}")

    print()
    print(f"{'=' * 60}")
    print(f"Batch complete: {len(summaries)} succeeded, {len(errors)} failed")
    print()

    for s in summaries:
        print(f"  {s['model_name']}: {s['health']} | "
              f"{s['assumption_count']} assumptions, "
              f"{s['kpi_count']} KPIs, "
              f"{s['hardcode_count']} hardcodes")

    if errors:
        print()
        print("Errors:")
        for e in errors:
            print(f"  {e['file']}: {e['error']}")


def _analyze_single_model(excel_path: str, output_dir: str) -> dict:
    """Run the full pipeline on a single model. Returns a summary dict."""
    basename = Path(excel_path).stem
    report_path = os.path.join(output_dir, f"{basename}_report.html")

    start = time.time()

    analysis = run_pipeline(excel_path)
    results = analysis.results
    property_name = results["metadata"]["property_name"]
    cells = analysis.cells
    graph_stats = results["graph_stats"]
    assumptions_list = results["assumptions"]
    hardcodes = results["hardcodes"]
    kpis = results["kpis"]
    complexity = results["complexity"]
    formula_count = results["cells_summary"]["formula_count"]
    sheet_names = results["metadata"]["sheet_names"]

    generate_report(results, report_path)

    elapsed = time.time() - start

    warning_count = sum(
        1 for h in hardcodes if h.get("severity") in ("warning", "error")
    )
    if warning_count <= 2:
        health = "Healthy"
    elif warning_count <= 5:
        health = "Minor Issues"
    else:
        health = "Needs Review"

    return {
        "file": excel_path,
        "model_name": basename,
        "property_name": property_name,
        "report_path": report_path,
        "health": health,
        "elapsed": round(elapsed, 1),
        "cell_count": len(cells),
        "formula_count": formula_count,
        "sheet_count": len(sheet_names),
        "assumption_count": len(assumptions_list),
        "kpi_count": len(kpis),
        "hardcode_count": len(hardcodes),
        "warning_count": warning_count,
        "graph_nodes": graph_stats["total_nodes"],
        "graph_edges": graph_stats["total_edges"],
        "complexity_score": complexity["score"],
        "complexity_grade": complexity["grade"],
        "assumptions": assumptions_list,
        "kpis": [
            {
                "name": k["name"],
                "value": k["value"],
                "formatted_value": k["formatted_value"],
                "cell_ref": k["cell_ref"],
            }
            for k in kpis
        ],
    }


def _generate_portfolio_csv(summaries: list, output_path: str) -> None:
    """Generate a CSV with assumptions and KPIs across all models."""
    all_assumption_names = sorted({a["name"] for s in summaries for a in s["assumptions"]})
    all_kpi_names = sorted({k["name"] for s in summaries for k in s["kpis"]})

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        header = ["Model", "Property", "Health", "Cells", "Formulas", "Assumptions", "KPIs", "Hardcodes"]
        for name in all_assumption_names:
            header.append(f"Assumption: {name}")
        for name in all_kpi_names:
            header.append(f"KPI: {name}")
        writer.writerow(header)

        for s in summaries:
            row = [
                s["model_name"], s["property_name"], s["health"],
                s["cell_count"], s["formula_count"], s["assumption_count"],
                s["kpi_count"], s["hardcode_count"],
            ]
            assumption_map = {a["name"]: a["value"] for a in s["assumptions"]}
            for name in all_assumption_names:
                row.append(assumption_map.get(name, ""))
            kpi_map = {k["name"]: k["formatted_value"] for k in s["kpis"]}
            for name in all_kpi_names:
                row.append(kpi_map.get(name, ""))
            writer.writerow(row)


def _generate_portfolio_html(summaries: list, output_path: str) -> None:
    """Generate a portfolio-level summary HTML report."""
    import html as html_module

    def esc(text):
        if text is None:
            return ""
        return html_module.escape(str(text))

    total = len(summaries)
    healthy = sum(1 for s in summaries if s["health"] == "Healthy")
    minor = sum(1 for s in summaries if s["health"] == "Minor Issues")
    needs_review = sum(1 for s in summaries if s["health"] == "Needs Review")

    model_rows = ""
    for s in summaries:
        health_cls = {
            "Healthy": "health-green",
            "Minor Issues": "health-yellow",
            "Needs Review": "health-red",
        }.get(s["health"], "")
        model_rows += f"""<tr>
  <td><a href="{esc(Path(s['report_path']).name)}">{esc(s['model_name'])}</a></td>
  <td>{esc(s['property_name'])}</td>
  <td><span class="{health_cls} health">{esc(s['health'])}</span></td>
  <td style="text-align:right">{s['cell_count']}</td>
  <td style="text-align:right">{s['assumption_count']}</td>
  <td style="text-align:right">{s['kpi_count']}</td>
  <td style="text-align:right">{s['hardcode_count']}</td>
  <td style="text-align:right">{s['elapsed']}s</td>
</tr>"""

    all_kpi_names = sorted({k["name"] for s in summaries for k in s["kpis"]})
    kpi_header = "".join(f"<th>{esc(name)}</th>" for name in all_kpi_names)
    kpi_rows = ""
    for s in summaries:
        kpi_map = {k["name"]: k["formatted_value"] for k in s["kpis"]}
        cells_html = "".join(
            f"<td style='text-align:right'>{esc(kpi_map.get(name, 'N/A'))}</td>"
            for name in all_kpi_names
        )
        kpi_rows += f"<tr><td>{esc(s['model_name'])}</td>{cells_html}</tr>"

    assumption_freq = {}
    for s in summaries:
        for a in s["assumptions"]:
            assumption_freq[a["name"]] = assumption_freq.get(a["name"], 0) + 1
    common_assumptions = sorted(assumption_freq.items(), key=lambda x: -x[1])[:20]
    common_names = [name for name, _ in common_assumptions]

    assumption_header = "".join(f"<th>{esc(name)}</th>" for name in common_names)
    assumption_rows = ""
    for s in summaries:
        a_map = {a["name"]: a["value"] for a in s["assumptions"]}
        cells_html = ""
        for name in common_names:
            val = a_map.get(name, "")
            if isinstance(val, float) and 0 < val < 1:
                display = f"{val:.1%}"
            elif isinstance(val, (int, float)):
                display = f"{val:,.0f}" if abs(val) >= 10 else str(val)
            else:
                display = esc(str(val)) if val != "" else ""
            cells_html += f"<td style='text-align:right'>{display}</td>"
        assumption_rows += f"<tr><td>{esc(s['model_name'])}</td>{cells_html}</tr>"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Summary</title>
<style>
:root {{
  --bg: #f8f9fa; --card: #ffffff; --border: #dee2e6;
  --text: #212529; --text-muted: #6c757d;
  --accent-blue: #0d6efd; --accent-green: #198754;
  --accent-amber: #fd7e14; --accent-red: #dc3545;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
}}
*, *::before, *::after {{ box-sizing: border-box; }}
body {{ font-family: var(--font); color: var(--text); background: var(--bg); margin: 0; padding: 2rem; line-height: 1.5; }}
h1 {{ font-size: 1.8rem; border-bottom: 3px solid var(--accent-blue); padding-bottom: 0.5rem; }}
h2 {{ font-size: 1.3rem; border-bottom: 2px solid var(--accent-blue); padding-bottom: 0.3rem; margin-top: 2rem; }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; margin-bottom: 1rem; }}
.card-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 0.75rem; }}
.stat-card {{ text-align: center; padding: 1rem; }}
.stat-card .num {{ font-size: 1.8rem; font-weight: 700; color: var(--accent-blue); }}
.stat-card .lbl {{ font-size: 0.78rem; color: var(--text-muted); text-transform: uppercase; }}
.health {{ display: inline-block; padding: 0.2rem 0.6rem; border-radius: 6px; font-weight: 700; font-size: 0.8rem; }}
.health-green {{ background: #d1e7dd; color: var(--accent-green); }}
.health-yellow {{ background: #fff3cd; color: #664d03; }}
.health-red {{ background: #f8d7da; color: var(--accent-red); }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
th {{ background: #f1f3f5; text-align: left; padding: 0.5rem 0.6rem; border-bottom: 2px solid var(--border); position: sticky; top: 0; }}
td {{ padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; }}
tr:nth-child(even) td {{ background: #fafbfc; }}
.table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 6px; }}
a {{ color: var(--accent-blue); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>Portfolio Summary</h1>
<p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")} | {total} models analyzed</p>

<div class="card-grid">
  <div class="card stat-card"><div class="num">{total}</div><div class="lbl">Models</div></div>
  <div class="card stat-card"><div class="num" style="color:var(--accent-green)">{healthy}</div><div class="lbl">Healthy</div></div>
  <div class="card stat-card"><div class="num" style="color:#664d03">{minor}</div><div class="lbl">Minor Issues</div></div>
  <div class="card stat-card"><div class="num" style="color:var(--accent-red)">{needs_review}</div><div class="lbl">Needs Review</div></div>
</div>

<h2>Model Overview</h2>
<div class="table-wrap">
<table>
<tr><th>Model</th><th>Property</th><th>Health</th><th>Cells</th><th>Assumptions</th><th>KPIs</th><th>Hardcodes</th><th>Time</th></tr>
{model_rows}
</table>
</div>

<h2>KPI Comparison</h2>
<div class="table-wrap">
<table>
<tr><th>Model</th>{kpi_header}</tr>
{kpi_rows}
</table>
</div>

<h2>Assumption Comparison</h2>
<div class="table-wrap">
<table>
<tr><th>Model</th>{assumption_header}</tr>
{assumption_rows}
</table>
</div>

</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(page)


def _require(value, flag: str, tool: str) -> str:
    if not value:
        raise ValueError(f"'{tool}' needs {flag}")
    return value


def cmd_query(args):
    """Print a query result as JSON on stdout (nothing else); errors are JSON too, exit code 2."""
    import json

    from xlens import query as q
    from xlens.analysis import load

    try:
        a = load(args.file)
        if args.tool == "overview":
            out = q.overview(a)
        elif args.tool == "trace":
            out = q.trace(a, _require(args.cell, "--cell", "trace"), args.direction, args.depth)
        elif args.tool == "find":
            out = q.find(a, _require(args.text, "--text", "find"))
        elif args.tool == "drivers":
            out = q.drivers(a, _require(args.cell, "--cell", "drivers"))
        else:
            out = q.findings(a, args.kind)
    except (AnalysisError, q.CellNotFound, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        raise SystemExit(2) from exc
    except Exception as exc:  # noqa: BLE001 - agents parse stdout, so never leak a traceback there
        if os.environ.get("XLENS_DEBUG"):
            traceback.print_exc()
        print(json.dumps({"error": f"Unexpected error: {type(exc).__name__}: {exc}"}))
        raise SystemExit(2) from exc
    print(json.dumps(out, indent=2, default=str))


def cmd_mcp(args):
    """Run the MCP server over stdio (stdout carries the protocol; never print here)."""
    from xlens.mcp_server import serve  # lazy: the server module is optional at import time

    serve(open_browser=not args.no_browser, viewer=not args.no_viewer)


def main():
    parser = argparse.ArgumentParser(
        prog="xlens",
        description="Excel model reverse-engineering and analysis toolkit",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # analyze subcommand
    p_analyze = subparsers.add_parser("analyze", help="Analyze a single Excel model")
    p_analyze.add_argument("file", help="Path to the Excel (.xlsx) file")
    p_analyze.add_argument("--output", "-o", help="Output HTML report path (default: output/<stem>_report.html)")

    # batch subcommand
    p_batch = subparsers.add_parser("batch", help="Batch analyze all Excel models in a directory")
    p_batch.add_argument("directory", help="Directory to search for .xlsx files")
    p_batch.add_argument("--output-dir", "-o", help="Output directory (default: output/)")

    p_query = subparsers.add_parser("query", help="Query a workbook and print JSON (for scripts and AI agents)")
    p_query.add_argument("tool", choices=["overview", "trace", "find", "drivers", "findings"])
    p_query.add_argument("file", help="Path to the Excel (.xlsx) file")
    p_query.add_argument("--cell", help="Cell reference, e.g. 'Cash Flow!C11' (trace, drivers)")
    p_query.add_argument("--text", help="Search text (find)")
    p_query.add_argument("--direction", default="up", choices=["up", "down", "both"])
    p_query.add_argument("--depth", type=int, default=1)
    p_query.add_argument("--kind", default="all", choices=["all", "hardcodes", "circular"])

    p_mcp = subparsers.add_parser("mcp", help="Run the Xlens MCP server over stdio (used by Claude and Codex)")
    p_mcp.add_argument("--no-browser", action="store_true", help="Never open the map in a browser")
    p_mcp.add_argument("--no-viewer", action="store_true", help="Do not start the local map viewer")

    args = parser.parse_args()

    if args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "batch":
        cmd_batch(args)
    elif args.command == "query":
        cmd_query(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
