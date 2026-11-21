"""The standalone map page: the Viewer's browser tab and the MCP App both render it."""
from __future__ import annotations

import json
import re

from xlens.report_generator import _TEMPLATE_DIR, _load_template, _script_safe_json

_SLOT = re.compile(r"/\*(CSS|EXPLORER|BRIDGE|DATA|MODE)\*/")


def _bridge() -> str:
    # The inline page is useless without the MCP Apps bridge (it is how data arrives), so a missing
    # template is a packaging error, not something to paper over.
    path = _TEMPLATE_DIR / "mcp_bridge.js"
    if not path.is_file():
        raise FileNotFoundError(f"MCP Apps bridge template missing: {path.name}")
    return _load_template("mcp_bridge.js")


def render_page(payload, mode: str) -> str:
    """mode='tab' loads /model.json + /events; mode='inline' embeds payload and uses the MCP Apps bridge."""
    if mode not in ("tab", "inline"):
        raise ValueError("mode must be 'tab' or 'inline'")
    parts = {
        "CSS": _load_template("report.css"),
        "EXPLORER": _load_template("explorer.js"),
        "BRIDGE": _bridge() if mode == "inline" else "",
        "DATA": _script_safe_json(json.dumps(payload, default=str)) if payload is not None else "null",
        "MODE": json.dumps(mode),
    }
    # One pass over the shell only: inserted text (CSS, scripts, workbook data) is never rescanned,
    # so a label such as "/*MODE*/" stays data.
    return _SLOT.sub(lambda m: parts[m.group(1)], _load_template("map_shell.html"))
