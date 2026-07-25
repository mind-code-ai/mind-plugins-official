# mind-plugins-official

The official plugin marketplace for [Mind](https://mindcode.sh)

## Install the marketplace

| Tool | Command |
| --- | --- |
| Mind | `/plugin marketplace add authninja-ai/mind-plugins-official` |
| Claude Code | `/plugin marketplace add authninja-ai/mind-plugins-official` |
| Augment Code | `/plugin marketplace add authninja-ai/mind-plugins-official` |

Then install any plugin listed below:

```
/plugin install my-first-plugin@mind-plugins-official
```

Plugin commands are namespaced by plugin name — the example above adds:

```
/my-first-plugin:greet Ada
```

## Plugins

| Plugin | Description |
| --- | --- |
| [my-first-plugin](plugins/my-first-plugin) | A greeting plugin to learn the basics |

## Plugin structure

Mind's native convention is `.mind-plugin/` — it takes precedence when
present. For cross-tool compatibility, plugins in this marketplace also carry
`.claude-plugin/` and `.augment-plugin/` copies of the same manifest:

```
my-first-plugin/
├── .mind-plugin/plugin.json      # Mind (native, wins when present)
├── .claude-plugin/plugin.json    # Claude Code compatibility
├── .augment-plugin/plugin.json   # Augment Code compatibility
├── commands/                     # slash commands (markdown)
├── skills/                       # skills (SKILL.md directories)
├── agents/                       # agent personas
└── hooks/ · mcp/                 # hooks and MCP server configs
```

`plugin.json` is the same shape everywhere:

```json
{
  "name": "my-first-plugin",
  "description": "A greeting plugin to learn the basics",
  "version": "1.0.0",
  "author": {
    "name": "Your Name"
  }
}
```

The marketplace itself is declared once per convention
(`.mind-plugin/marketplace.json` and compatibility copies):

```json
{
  "name": "mind-plugins-official",
  "owner": { "name": "thebrightondev" },
  "plugins": [
    { "name": "my-first-plugin", "source": "./plugins/my-first-plugin" }
  ]
}
```

## Contributing a plugin

1. Add a directory under `plugins/<your-plugin>/` with the three manifest
   copies and your components (`commands/`, `skills/`, …).
2. Register it in all three `marketplace.json` files (keep them identical).
3. Open a PR. CI checks that the manifests parse and stay in sync.

Full documentation: <https://mindcode.sh/docs/en/plugins>
