# Install notes: Claude Code and Codex plugins

What was checked by hand on 2026-11-16, and what was not. `<repo>` is the checkout and `<tmp>` is a throwaway folder.

Versions: Claude Code 2.1.322, codex-cli 0.159.3, uv/uvx 0.10.8, Linux (WSL2).

**Not verified:** the published install command `uvx --from xlens-ai xlens mcp`. The `xlens-ai` package is not on PyPI yet. Every run below swapped that command for the local `<repo>/.venv/bin/xlens mcp --no-browser`, and only in a temporary copy of the plugin. The committed `.mcp.json` files still use `uvx`.

## Recommended install

| Host | Command |
|---|---|
| Claude Code | `claude plugin marketplace add akay126/xlens`, then `claude plugin install xlens@xlens` |
| Codex | `codex plugin marketplace add akay126/xlens`, then `codex plugin add xlens@xlens` |
| Codex, MCP only (no skill) | `codex mcp add xlens -- uvx --from xlens-ai xlens mcp` |
| Any other MCP host | stdio server, command `uvx --from xlens-ai xlens mcp` |

The `owner/repo` marketplace form was not tested, because this branch is not pushed. Only the local-path form was run. The skill source is `skills/xlens/SKILL.md`. After editing it, run `python scripts/sync_plugins.py` to copy it into both plugins. `tests/test_plugins.py` fails if the copies are stale.

## Claude Code: verified

- `claude plugin validate --strict plugins/claude` passes. The only warning is a plugin-directory advisory about a missing icon, and it does not fail `--strict`.
- `claude plugin validate --strict .` (the marketplace) passes. It first needed a top-level `description` in `.claude-plugin/marketplace.json`.
- The install was run with `CLAUDE_CONFIG_DIR=<tmp>/cfg` against a git copy of the marketplace:
  - `claude plugin marketplace add <tmp>/mkt` printed "Successfully added marketplace: xlens".
  - `claude plugin install xlens@xlens` printed "Successfully installed plugin: xlens@xlens".
  - `claude plugin list` showed `xlens@xlens`, version 0.2.0, enabled.
  - `claude mcp list` showed `plugin:xlens:xlens: uvx --from xlens-ai xlens mcp` failing to connect. That is expected while the package is unpublished.
- End to end, using a copy of `plugins/claude` whose `.mcp.json` pointed at the local venv:
  - Command: `claude --plugin-dir <tmp>/local -p "Use the xlens tools to analyze <repo>/examples/sample_model.xlsx and tell me what drives Net Operating Income in year 5. Cite cells." --output-format stream-json --verbose --allowedTools mcp__plugin_xlens_xlens__*`. The six tools were listed one by one.
  - The init event showed server `plugin:xlens:xlens` connected, the six tools present, and the skill `xlens:xlens` loaded.
  - The agent invoked the `xlens:xlens` skill, then called `analyze_model`, `find("NOI")`, `trace("Cash Flow!G11", up, 2)`, `drivers`, `findings("hardcodes")`, another `trace` and `show`.
  - It answered "Year 5 NOI is Cash Flow!G11 = $523,811", ranked the drivers (Rent Growth `Inputs!B8`, Units `Inputs!B3`, and so on), and flagged the typed-in `Cash Flow!F9 = $215,000`.
- Not verified: the browser tab opening. The run used `--no-browser`. The map URL was returned and quoted by the agent.

## Codex: verified, including stdio MCP servers in a plugin

**Codex plugin install verified with codex-cli 0.159.3** (install, skill and MCP server discovery, and a direct tool call; no model session ran through the plugin, see below).

**Answer: Codex plugins do support stdio MCP servers.** The plugin needs `.codex-plugin/plugin.json` with `"mcpServers": "./.mcp.json"`, and `.mcp.json` uses `command`/`args`. OpenAI's own curated plugins use the same layout, for example `build-ios-apps`, which runs `npx`.

These checks used `CODEX_HOME=<tmp>/home` and a git copy of the repo's `.agents/` and `plugins/` folders. No credentials were in that home.

- `codex plugin marketplace add <tmp>/mkt` printed "Added marketplace `xlens`".
- `codex plugin list` showed `xlens@xlens  not installed`. After `codex plugin add xlens@xlens` it showed `installed, enabled  0.2.0`.
- `codex debug prompt-input hi` listed the skill as `xlens:xlens: Explain and check Excel (.xlsx) financial models ...`.
- `codex mcp list` showed `xlens  <command>  mcp --no-browser  enabled`. While the root `plugin.json` layout was in use, it showed nothing.
- A JSON-RPC probe of `codex app-server --stdio` did `initialize`, then `thread/start`, then `mcpServerStatus/list` with the thread id.
  - It returned server `xlens` with `pluginId: xlens@xlens` and tools `analyze_model, drivers, find, findings, show, trace`.
  - Calling `mcpServer/tool/call` with `trace` on `Cash Flow!G11` returned `Net Operating Income`, `=G7-G9`, value 523811.43.
- Layout findings from bisecting against the curated `build-ios-apps` plugin as a control:
  - The marketplace `policy` must be an object (`{"installation": "AVAILABLE", "authentication": "ON_INSTALL"}`). A string such as `"allow"` is rejected. `source` is `{"source": "local", "path": ...}`.
  - Whenever a root-level `plugin.json` (agent-plugins 1.0 `$schema`) was present, with or without `.codex-plugin/plugin.json` beside it, the skill loaded but no MCP server started, even when it held `skills`/`mcpServers` pointers and even with a `CODEX_HOME` outside `/tmp`. So the Codex plugin ships only `.codex-plugin/plugin.json`.
  - `"type": "stdio"` in `.mcp.json` is accepted.
- A model-driven run on the real Codex home used only per-invocation overrides and wrote no config files:
  - Command: `codex exec --ephemeral --skip-git-repo-check -c 'mcp_servers.xlens.command="<repo>/.venv/bin/xlens"' -c 'mcp_servers.xlens.args=["mcp","--no-browser"]' "<same prompt>"`.
  - This shows the MCP server works under Codex. It does not exercise the plugin install path. The result is recorded below.

  - Other MCP servers configured on the test machine also loaded and were sometimes consulted, so this run shows the xlens tools work end to end, not that every sentence of the answer came only from xlens.
  - Result: Codex called `analyze_model`, `drivers("Cash Flow!G11")`, `trace` (up, depth 5), `findings("hardcodes")`, `find` (twice), another `trace` and `show`, and every call completed.
  - It answered "Year 5 Net Operating Income is $523,811 (`Cash Flow!G11`), calculated as `=G7-G9`", cited each component and input cell, and flagged the typed-in `Cash Flow!F9 = $215,000`.
  - Without `< /dev/null`, `codex exec` waits for more input on stdin and appears to hang.

Not verified for Codex: a full model session that loads the server through the installed plugin. The temporary home had no credentials, and the real home was not modified.
