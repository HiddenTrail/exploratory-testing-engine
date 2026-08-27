---
type: Quality Concept
title: "{{TITLE}}"
description:            # ONE sentence — this is what wiki/index.md shows for the page
tags: []
status: draft           # draft | stable | deprecated (absent ⇒ stable)
generated: { by: human:{{AUTHOR}}, at: "{{TIMESTAMP}}" }
# verified: { by: human:<id>, at: "<ISO 8601 UTC>" }
sources:
  - id: <short-key>
    resource: raw/<file>         # REQUIRED per entry
    title: <human-readable label>
guidelines_refs: []     # QPF extension: Guidelines IDs this relates to, e.g. ["2.1","4.3"]
# stale_after: "<ISO 8601 UTC>"
---

# {{TITLE}}

<!-- One page per quality concept or finding: a Definition of Done, a quality gate, a
     Value-Stream-Mapping finding, a risk, a way of working. These feed the Guidelines
     tailoring and the playbook glossary. Cite raw/ sources with footnotes keyed to
     `sources[].id`; link Guidelines IDs in `guidelines_refs`. -->

## What it is

## Current state / findings

## Implications for Guidelines / Playbook

[^<short-key>]: <human-readable label of the source>
