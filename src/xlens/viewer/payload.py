"""Model JSON consumed by explorer.js (report, tab and MCP App all use the same shape)."""
from __future__ import annotations

import json

from xlens.query import MAX_SCENARIOS, _text, findings, overview


def _kpis(a) -> list:
    """Every KPI with its scenario columns (uncapped, unlike overview(), whose output must fit a tool reply)."""
    t = lambda x: _text(x)[0]  # noqa: E731
    return [{"name": t(k["name"]), "cell": k["cell_ref"], "display": t(k.get("formatted_value", "")),
             "scenarios": [{"cell": s["cell_ref"], "header": t(s["header"]), "display": t(s["formatted_value"])}
                           for s in k.get("scenarios", [])[:MAX_SCENARIOS]]}
            for k in a.results["kpis"] if k.get("cell_ref")]


def build_payload(a) -> dict:
    graph = json.loads(a.results["graph_json"])
    nodes = [n for n in graph["nodes"] if n.get("in_degree") or n.get("out_degree")]
    return {
        "model": overview(a)["model"],
        "nodes": nodes,
        "links": graph["links"],
        "kpis": _kpis(a),
        "findings": [{"cell": i.get("cell") or i["cells"][0], "kind": i["kind"], "severity": i["severity"]}
                     for i in findings(a, "all", cap=False)["items"]],
    }
