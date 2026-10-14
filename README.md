# divramod-claude-code-plugins

divramod's Claude Code plugins, one marketplace: agent skills and live panes for Claude Code.

| Plugin | What it is |
|---|---|
| [divramod-skills](plugins/divramod-skills) | The agent skills: plans, grills, handoffs, landings, research, summaries of anything (`/divramod-skills:<skill>`). Also a Codex plugin. |
| [hal2-mcp](plugins/hal2-mcp) | The `hal2-cli-mcp` MCP server (needs the binary on `PATH`). Also a Codex plugin. |
| [divramod-subagent-context](plugins/divramod-subagent-context) | A mod: a live pane of every subagent of the session with its model, effort, context fill, peak and compactions. |

## Install

```
claude plugin marketplace add divramod/divramod-claude-code-plugins
claude plugin install divramod-skills@divramod-claude-code-plugins
claude plugin install divramod-subagent-context@divramod-claude-code-plugins
claude plugin install hal2-mcp@divramod-claude-code-plugins
```

In a session the same works as `/plugin marketplace add divramod/divramod-claude-code-plugins`, then `/plugin`.
Codex finds its marketplace in `.agents/plugins/marketplace.json` (the skills and hal2-mcp) when this repository is added
as a Codex marketplace.

## Update

An installed plugin updates when its version changes:

```
claude plugin marketplace update divramod-claude-code-plugins
claude plugin update divramod-skills@divramod-claude-code-plugins
claude plugin update divramod-subagent-context@divramod-claude-code-plugins
claude plugin update hal2-mcp@divramod-claude-code-plugins
```

Restart Claude Code afterwards, or turn on auto-update for this marketplace in `/plugin` under Marketplaces.

## How it is released

This repository is a mirror. Every plugin is developed in [divramod/hal2](https://github.com/divramod/hal2)
(`code/claude-code/apps/<name>`), and every landing there that changes a plugin publishes it here: the plugin's
tracked files go to `plugins/<name>/`, the marketplace files are generated from the plugins' `plugin.json`, and one
commit names the hal2 commit it came from (`Hal2-Source`, `Hal2-Tree` trailers). hal2's landing bumps a plugin's
version and the publish tags it (`<plugin>--v<version>`).

Do not edit this repository by hand: the next publish overwrites a hand edit. Issues and pull requests are welcome
here; a fix is carried over into hal2. The CI here (`.github/workflows/ci.yml`) validates the marketplace and every
plugin and runs their tests on each push.

## License

MIT, see [LICENSE](LICENSE).
