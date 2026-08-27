---
type: Entity
entity_kind: person | role | team | system | tool | environment
title: "{{TITLE}}"
description:            # ONE sentence — this is what wiki/index.md shows for the page
tags: []
status: draft           # draft | stable | deprecated (absent ⇒ stable)
# resource: <URI>       # canonical URI when the entity is a real system/tool/environment
generated: { by: human:{{AUTHOR}}, at: "{{TIMESTAMP}}" }
# verified: { by: human:<id>, at: "<ISO 8601 UTC>" }
sources:
  - id: <short-key>
    resource: raw/<file>         # REQUIRED per entry
    title: <human-readable label>
---

# {{TITLE}}

<!-- One page per entity. Keep it factual and sourced. Link related entities and the
     concepts/summaries that reference it with plain relative markdown links — a link
     is an untyped edge, so say what the relationship IS in the surrounding prose. -->

- **Kind:** <person | role | team | system | tool | environment>
- **Summary:** <one line>

## Details

## Related

[^<short-key>]: <human-readable label of the source>
