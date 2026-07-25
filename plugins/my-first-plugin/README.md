# my-first-plugin

The smallest useful plugin: one slash command, three one-line manifests.
Use it as the template for your own plugins.

```
/plugin install my-first-plugin@mind-plugins-official
/greet Ada
```

## Layout

- `.mind-plugin/plugin.json` — Mind's native manifest (takes precedence)
- `.claude-plugin/plugin.json` / `.augment-plugin/plugin.json` — identical
  copies for Claude Code and Augment Code
- `commands/greet.md` — the `/greet` command: frontmatter `description` plus
  the instruction text sent through the agent loop when the command runs
