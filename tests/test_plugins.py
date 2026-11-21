import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_skill_copies_match_source():
    src = (ROOT / "skills/xlens/SKILL.md").read_text()
    for p in ("plugins/claude/skills/xlens/SKILL.md", "plugins/codex/skills/xlens/SKILL.md"):
        assert (ROOT / p).read_text() == src, f"{p} is stale: run python scripts/sync_plugins.py"


def test_skill_front_matter():
    text = (ROOT / "skills/xlens/SKILL.md").read_text()
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1)
    assert re.search(r"^name: xlens$", fm, re.M) and re.search(r"^description: .{40,}", fm, re.M)
    assert "untrusted" in text.lower() and "Sheet!Ref" in text


@pytest.mark.parametrize("path", ["plugins/claude/.claude-plugin/plugin.json", "plugins/claude/.mcp.json",
                                  ".claude-plugin/marketplace.json", "plugins/codex/.codex-plugin/plugin.json",
                                  "plugins/codex/.mcp.json", ".agents/plugins/marketplace.json"])
def test_manifests_parse(path):
    json.loads((ROOT / path).read_text())


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
def test_claude_validate():
    for target in ("plugins/claude", "."):
        r = subprocess.run(["claude", "plugin", "validate", "--strict", target], cwd=ROOT, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("path", ["plugins/claude/.mcp.json", "plugins/codex/.mcp.json"])
def test_mcp_config_launches_xlens_via_uvx(path):
    server = json.loads((ROOT / path).read_text())["mcpServers"]["xlens"]
    assert server["command"] == "uvx"
    assert server["args"] == ["--from", "xlens-ai", "xlens", "mcp"]
