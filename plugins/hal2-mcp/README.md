# hal2-mcp

The plugin `hal2-mcp` (Claude Code and Codex): it declares the MCP server `hal2-mcp`, which starts `hal2-cli-mcp mcp` over stdio.

The plugin installs only that entry; the binary `hal2-cli-mcp` comes from hal2's installer and must be on `PATH` (without it the client shows the server as failed to start). Published to
[divramod/divramod-claude-code-plugins](https://github.com/divramod/divramod-claude-code-plugins) as
`plugins/hal2-mcp` by the publish job ([claude-code-plugins](../../../../.adr/claude-code-plugins.md)).

```
claude plugin install hal2-mcp@divramod-claude-code-plugins
```

In Claude Code the server is `plugin:hal2-mcp:hal2-mcp`, its tools `mcp__plugin_hal2-mcp_hal2-mcp__<tool>`.
OpenCode and Antigravity have no plugin route for MCP servers: `hal2-cli-mcp mcp install` writes their entries.

## Module map

- [.claude-plugin/plugin.json](.claude-plugin/plugin.json): the Claude Code manifest (name, version); the root
  [.mcp.json](.mcp.json) is loaded by Claude Code without being named.
- [.codex-plugin/plugin.json](.codex-plugin/plugin.json): the Codex manifest, `mcpServers` points to the same `.mcp.json`.
- [.mcp.json](.mcp.json): `{"mcpServers": {"hal2-mcp": {"command": "hal2-cli-mcp", "args": ["mcp"]}}}`.

## Another CLI

A `hal2-cli-<domain>` that adopts `hal2_core::cli` adds its server as one more entry in `.mcp.json`, named
`hal2-<domain>`, with `"command": "hal2-cli-<domain>"` and `"args": ["mcp"]`; raise both manifests' `version` so
installed plugins update.
