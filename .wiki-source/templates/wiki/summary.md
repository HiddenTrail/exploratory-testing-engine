---
type: Source Summary
title: "{{TITLE}}"
description:            # ONE sentence — this is what wiki/index.md shows for the page
tags: []
status: draft           # draft | stable | deprecated (absent ⇒ stable)
generated: { by: human:{{AUTHOR}}, at: "{{TIMESTAMP}}" }
# verified: { by: human:<id>, at: "<ISO 8601 UTC>" }   # add on review → human-reviewed
sources:
  - id: <short-key>              # join key for body footnotes: [^<short-key>]
    resource: raw/<file>         # REQUIRED per entry — what this digests
    title: <human-readable label>
    # author: human:<id>         # who produced the source (authority signal)
    # last_modified: "<ISO 8601 UTC>"
# stale_after: "<ISO 8601 UTC>"  # set when the content has a known shelf life
---

# {{TITLE}}

<!-- A faithful digest of ONE raw source (workshop, interview, or assessment).
     Capture: context, key points, decisions, risks, and open questions. Do not add
     interpretation the source doesn't support.

     OKF v0.2: attribute individual claims with a markdown footnote whose label is a
     `sources[].id` — the label is the join key, so it survives reordering. Prefer
     structural markdown (headings, lists, tables) over freeform prose. -->

## Key points

## Decisions & commitments

## Risks & open questions

[^<short-key>]: <human-readable label of the source>
