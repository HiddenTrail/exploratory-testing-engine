# Ontology layer reference

Ground-truth documentation of the 4-layer ontology stack implemented under
`engine/ontology/` (Phase 0, proven on `token_purchase` — see
[`docs/ontology-todo.md`](ontology-todo.md) for status and backlog). Written
layer by layer, from the actual current files, not from the design
discussion that led here.

## Layer 1 — Heuristic library

**File:** [`engine/ontology/heuristics.json`](../engine/ontology/heuristics.json)

### What it is

Layer 1 is the part of the system that knows nothing about any specific
product. It's a small library of testing heuristics that apply to *any*
system — the kind of thing an experienced tester already carries in their
head before ever seeing a spec. These entries describe *kinds* of things
worth checking, not facts about `token_purchase` or any other particular
SUT.

This is distinct from `experiments/oracle-agent-poc/heuristics/catalog.json`,
a larger HTSM-seeded reference catalog (31 entries, SFDIPOT/Quality
Criteria/General Test Techniques/FEW-HICCUPPS) — layer 1 is the small,
*active* subset actually wired into scoring, not the full reference list.

### Why it's a separate layer

It's reusable. Build it once, and it doesn't get rebuilt or thrown away
when the same testing engine points at a different product next quarter —
unlike the domain and context layers below it, which are specific to one
SUT and get re-derived every time.

### The test for whether something belongs here

*Would this heuristic still make sense if I swapped in a completely
different product tomorrow — a payment API, a hospital scheduling system, a
game inventory?* If yes, it belongs in layer 1. If answering that requires
knowing this product's actual field names, business rules, or a specific
ticket/incident, it belongs a layer down instead (domain, if it's a fact
about this SUT; context, if it's a fact about this SUT's history).

In practice, ideas that come from real tester experience split into three
tiers, and only the first belongs here:

1. **Truly universal** — e.g. "check zero/negative for any positive-quantity
   field," "check monetary precision." Works on any system anywhere. →
   Layer 1.
2. **Company/domain-wide, not universal** — patterns an organization keeps
   re-learning across *its own* systems (e.g. "our microservices always
   mishandle timezone conversion at DST boundaries"). Real and valuable,
   but scoped to a company or industry, not to any system on earth. A
   distinct tier from what's in `heuristics.json` today, not yet
   represented here.
3. **Product-specific war stories** — e.g. "the `/purchase` endpoint always
   chokes on negative `credit_count`." Not layer 1 even if it started as
   hard-won intuition — either abstract it first (that example already
   generalizes to `zero_and_negative`, which *is* in the catalog), or file
   it under layer 2/3, tagged to that specific SUT.

Skipping this filter is the main risk: pour in tester intuition unfiltered,
and layer 1 turns into a junk drawer of one-off product folklore that
doesn't actually transfer — which defeats the reason it's a separate layer
at all.

**Worked example:** `goldilocks` ("test too small, just right, too big for
any bounded field") passes cleanly — it names no product, no field, and
is itself a named heuristic from established exploratory-testing literature
(Elisabeth Hendrickson's test heuristics work), independent evidence it's
genuinely tier-1 rather than local folklore dressed up as universal. It
also isn't redundant with the neighboring `boundary_edges`: `goldilocks` is
broad equivalence partitioning (useful even with no documented limit, to
find where the boundary actually is), while `boundary_edges` is precise
off-by-one probing once a limit is known — complementary, not duplicate.

### Entries

Each entry: `id` (stable slug, referenced elsewhere as `heuristic:<id>`),
`category`, `description`, `base_weight` (integer, used by
`oracle_creator.py` to seed a generic probe's starting priority before any
context-layer signal is applied).

| id | category | base_weight | description |
|---|---|---|---|
| `goldilocks` | boundary | 2 | Test too small, just right, and too big values for any bounded field. |
| `boundary_edges` | boundary | 2 | Test values exactly at, one below, and one above a documented limit. |
| `zero_and_negative` | boundary | 3 | Test zero and negative values for any field assumed to be a positive quantity. |
| `alphabet_soup` | data_type | 1 | Feed unicode, emoji, whitespace-only, and mixed-script strings into text fields. |
| `monetary_precision` | data_type | 3 | Check that monetary values never show float rounding artifacts and use consistent decimal precision. |
| `empty_and_null` | data_type | 2 | Submit empty string, null, and missing-field variants for every required field. |
| `duplicate_replay` | state | 2 | Repeat an identical request/transaction and check for idempotency or unintended duplication. |
| `ordering_race` | state | 1 | Fire near-simultaneous or out-of-order requests against the same resource/account. |
| `sensitive_data_exposure` | security | 3 | Check that sensitive fields (secrets, PANs, tokens) are never echoed back in responses or logs. |
| `self_consistency` | consistency | 2 | Compare two responses that should logically agree (e.g. same query, different path) for contradictions. |

10 entries, 5 categories (boundary, data_type, state, security,
consistency). `base_weight` ranges 1–3; `sensitive_data_exposure`,
`monetary_precision`, and `zero_and_negative` are the highest-weighted (3),
`alphabet_soup` and `ordering_race` the lowest (1) — reflecting the actual
risk/attention a bug in that category deserves before any SUT-specific
context adjusts it.

Not yet cross-referenced to the larger `catalog.json` reference list — the
31-entry HTSM catalog and this 10-entry active set currently evolve
independently; promoting a `catalog.json` entry into this file (or vice
versa) is manual, not automated.

## Layer 2 — Domain/spec layer

**File:** [`engine/ontology/domain_token_purchase.json`](../engine/ontology/domain_token_purchase.json)

### What it is

Layer 2 is the set of raw, stated facts about *this specific system* — what
it is, what it does, what it claims about itself. Not judgments about what's
worth testing (that's what layer 4 derives from this plus layers 1 and 3),
just the facts: the endpoint shape, the documented fields and their types,
the known error/decline reasons, the plain-language business rules, and any
fixed test fixtures (known accounts, sample data) needed to actually call
the thing.

Concretely, `domain_token_purchase.json` today holds: the endpoint
(method + path), `request_fields` / `response_fields` (name, type,
description), `known_decline_reasons` (the documented enum), `business_rules`
(plain-language facts like "pricing is tiered by bulk quantity" and "each
card has a spending capacity never revealed directly"), and `known_accounts`
(fixed fixtures).

### Cadence — why it's a separate layer from context

This is the layer that changes rarely — roughly sprint or quarter cadence,
not daily. It moves when the API contract itself moves: a new field, a new
decline reason, a pricing model rework, a new endpoint. That's a
fundamentally different rhythm than layer 3 (context), which is expected to
change constantly — new test results every day, new JIRA tickets whenever
they're filed — even when nothing about the product itself has changed.
Keeping them as separate files/layers, not one blended "everything we know
about this SUT" bucket, is what lets the pipeline treat them differently:
a domain-layer change is significant enough to justify **regenerating the
whole claim set from scratch** (heuristics × new domain facts), while a
context-layer change only **rescores the existing claims** (see Layer 4
below).

### The test for whether something belongs here

Is this a fact that would still be true even if no test had ever been run
and no ticket had ever been filed — something you'd find by reading the
spec or the code, not by watching the system's history? If yes, domain. If
it's instead "here's what happened when we tested this" or "here's what
someone flagged as a concern," that's context (layer 3), not domain, even
though both are "specific to this SUT."

### Known gap (as of this writing)

`domain_token_purchase.json` isn't actually read by the scoring pipeline
yet. `engine/ontology/oracle_creator.py`'s own docstring says layer 2 is
`adapters/<sut>/oracle_library.json` — a older, separate artifact from the
pre-4-layer Oracle Agent PoC, where a heuristic pass was already run once
over the spec by hand, producing pre-digested claims rather than raw facts.
`domain_token_purchase.json` is currently only read by `website.py`, for
display in the HTML report. The corrected design (per 2026-08-27
discussion): `oracle_creator.py` should read this file directly and derive
claims fresh each time (heuristics × domain), rather than consuming a
separately pre-baked claim set — collapsing the two artifacts into one.
Not yet implemented.

A second known gap: nothing here currently tags *which* fields are
sensitive/risk-relevant (e.g. `card_number`, `cvv` as PCI-relevant), which
layer 1's `sensitive_data_exposure` heuristic and layer 4's scoring would
need in order to weight those fields higher specifically *because* this SUT
handles them — right now that inference is left implicit rather than
stated as domain-layer content.

### Open question, not yet resolved

Where organizational/business-risk information belongs (e.g. "this touches
real money," "this is compliance-critical," "this area caused a
revenue-impacting incident last quarter") isn't fully settled. A rough
split: a fact about *this SUT specifically* belongs here once tagged (see
gap above); a *recent, evolving judgment* about this SUT belongs in layer
3's `risk_assessments` field (exists today, unused); a *standing policy
that applies org-wide across every SUT* doesn't fit either layer cleanly
(both are scoped per-SUT) and is being left unresolved until a concrete
case forces the question.

## Layer 3 — Context/source layer

**File:** [`engine/ontology/context_token_purchase.json`](../engine/ontology/context_token_purchase.json)

### What it is

Layer 3 is anything about *this specific product* that can change fast —
daily, hourly, sometimes minutely — for reasons that have nothing to do
with the code itself changing. The defining trait isn't a fixed list of
source types, it's **cadence**: a fact that's true today and might be false
tomorrow, in contrast to layer 2's sprint/quarter-stable facts and layer
1's never-changing generic vocabulary.

Implemented today as three arrays: `test_results` (outcomes fed back by
`engine/ontology/feedback.py` after a Driver run), `jira_entries`
(ticket-shaped signals), and `risk_assessments` (human-authored risk
judgments) — but these are examples of the class, not its definition.
Other things that clearly belong to the same class, not yet implemented:
a feature flag flipping, a deploy/release happening, an incident or
monitoring alert, a support ticket, an A/B test result, a config change, a
new security advisory — and commit messages / merge-request titles and
descriptions (see below).

### Cadence — why it's separate from domain

This is the fast-moving layer, in contrast to layer 2's sprint/quarter
cadence. A domain-layer change is rare enough to justify regenerating the
whole claim set; a context-layer change is common enough (every test run,
every ticket, potentially every commit) that it can't trigger a full
regeneration each time — it only *rescores* the claims that already exist.
That distinction is what lets the pipeline run a cheap update daily without
re-deriving everything from the spec every time.

### The test for whether something belongs here

Would this be stale or wrong if not refreshed within hours or days, as
opposed to something stable for a sprint or a quarter? If yes, context
(layer 3). If it's true regardless of how much time has passed or how much
testing has happened, it's domain instead (layer 2).

### Where code changes fit — and where they don't

Worth being explicit about, since it's easy to overreach here. Two
different things both look like "code changed":

- **A change that alters the SUT's actual behavior/contract** (new field,
  changed validation, reworked pricing) does *not* belong in layer 3
  directly — parsing a diff to infer new behavior duplicates layer 2's job
  and risks the oracle acting on a misread change instead of the actual
  current contract. The correct path is: the domain file gets updated,
  which is a layer-2 change, which triggers full regeneration as already
  designed.
- **A commit message or MR title/description as a risk/attention signal**
  belongs in layer 3, and fits the exact same mechanism `jira_entries`
  already uses: free text, keyword/relevance-matched against claims, to
  bump priority on areas someone was recently working in. Not used to
  derive facts — used as evidence that this area deserves more attention
  right now. (The general pattern "recently-changed code deserves more
  testing attention" is itself a generic heuristic and arguably belongs in
  layer 1; the specific fact of *which* files/commits and what they say is
  layer 3.)

### How it actually affects ranking (from `oracle_creator.py`)

Only two of the three arrays are wired into scoring today —
`score_grounded_claim` reads `test_results` and `jira_entries`;
`risk_assessments` is loaded but not yet consulted anywhere. Each grounded
claim starts at a base score (`GROUNDED_BASE_SCORE = 5.0`) and is adjusted:

| Context signal | Effect | Delta |
|---|---|---|
| No matching test result found | Untested — mild priority bump, worth trying | `+1.0` |
| Matching result, `verified: false` | Refuted — a real finding, jump to the top | `+4.0` |
| Matching result, `verified: true` | Confirmed and stale — deprioritize, it's settled | `−2.0` |
| Claim keyword-matches a `jira_entries` title/description | Someone already flagged this as relevant | `+3.0` (stacks with the above) |

Matching a test result to a claim is by stable `claim_id`
(`claim:<category>:<index>`), not by text similarity — fixed after an
earlier bug where the Driver's free-text `linked_hypothesis` never matched
the claim's exact wording (see `docs/ontology-todo.md`, "claim-matching
gap"). `jira_entries` matching is currently a blunt keyword overlap
(`_jira_mentions`) — words over 4 characters shared between the claim text
and a ticket's title/description — not semantic matching.

### Current state

All three arrays are empty in `context_token_purchase.json` — no test
results, no JIRA entries, no risk assessments have been fed in yet on the
mock. The prior demo data was cleared when the claim-matching fix landed,
since it was keyed by claim text under the old, non-functional scheme (see
`docs/ontology-todo.md`).

### Known gap

`risk_assessments` has a slot in the file and in `load_context()`'s
default shape, but nothing in `score_grounded_claim` reads it yet — it's
placeholder structure, not a working input. This is also where the
"organizational/business-risk" question from the layer 2 discussion would
most likely land, once there's an actual scoring rule for it.

## Layer 4 — Oracle (ranking/scoring)

*Not yet documented here — file: `engine/ontology/oracle_creator.py`.*
