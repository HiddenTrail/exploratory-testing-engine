---
description: Scaffold a new customer quality workspace (Tier-3 repo) from the QPF templates.
argument-hint: "<customer name> [--language en|fi] [--dir <path>]"
allowed-tools: Bash(node:*), Bash(git:*), Read
---

Scaffold a new **customer quality workspace** using the Quality Playbook Factory
scaffolder.

Arguments given: `$ARGUMENTS`

Do this:

1. Parse the customer name (everything that isn't a `--flag`) and any `--language`
   (`en`|`fi`, default `en`) / `--dir` / `--force` flags from the arguments above.
   - If no customer name is present, ask for one and stop.
   - If `--language` is absent, tell the user it will default to **en** and that
     language is fixed for the workspace's lifetime — confirm before proceeding.
2. Run the scaffolder:
   ```
   node "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold.mjs" --customer "<name>" --language <lang> [--dir <path>] [--force]
   ```
3. Report the created path and the "Next steps" the script prints. Do **not** commit
   the new workspace automatically — leave that to the consultant.

The workspace is self-contained and tool-agnostic (its own AGENTS.md/CLAUDE.md); it
does not depend on this tool at runtime.
