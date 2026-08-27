# {{CUSTOMER}} — Quality workspace

The working conventions, layout, page types, and operations for this workspace are
defined in **[AGENTS.md](AGENTS.md)** — read it first. This file exists so that
Claude Code (and other tools that look for `CLAUDE.md`) pick up the same schema.

Quick reminders:

- This is a **customer quality workspace**, not application code. Its "build" outputs
  are the Quality Guidelines (`guidelines/`) and per-team Quality Playbooks
  (`playbooks/<team>/`).
- Everything is plain markdown in git; keep it tool-agnostic (no `[[wikilinks]]`, no
  Obsidian-only features). Language for all deliverables is set in `qpf.config.yml`.
- `wiki/index.md` and `guidelines/guidelines.md` are **derived** — regenerate them,
  don't hand-edit.
- Always cite `raw/` sources when answering questions about this customer.
