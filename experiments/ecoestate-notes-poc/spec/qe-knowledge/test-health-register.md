# Test Health Register

Last updated: 2026-04-21

Per-test stability observations accumulated across PR merges. Updated by merge consolidation
when CI test output is available in `qe/output/pr-<N>/test-analysis.md`.

Analytics source: `qe/knowledge/test-analytics/test_analytics_ecoestate_20260201_20260421.jsonl`
Registry source: `qe/knowledge/tests-registry.csv`

Note: Only tests with observed failures or instability are listed. Tests passing consistently
are not tracked here.

**Status vocabulary**:
- `At-Risk` — one or more failures observed but pattern too thin to confirm (< 3 PRs of data)
- `Flaky` — mixed pass/fail pattern across 3+ data points; confirmed instability
- `Real Failure` — fails consistently across all recent data points; likely product defect
- `Quarantined` — temporarily excluded from blocking builds; tracked separately from CI

**Heuristic flags** (mark with ✓ when observed):
- `intermittent` — failures interspersed with passes across ≥ 2 separate observations
- `high_fail_rate` — fail rate ≥ 20% across observed window
- `recent` — failure observed in the last PR touching this component

## Tracked Tests

| ID | Test / Suite | Component | Status | Flags | PRs Observed | Fail / Total | Last Seen PR | Linked KI | Owner |
|----|-------------|-----------|--------|-------|-------------|--------------|-------------|-----------|-------|
| TH-2026-001 | `notesRoutes.test.ts` — `should list all notes for a postcode (returns in insertion order)` | server:notes | At-Risk | recent | #23 | 1 / 3 | #23 | KI-2026-008 | - |
| TH-2026-002 | `walkingDistanceRoutes.test.ts` — `should return 5min category when postcode is within 400m of a metro or railway station` | server:api | Flaky | intermittent, high_fail_rate | #10, #17, #23 | 2 / 8 | #23 | — | - |
| TH-2026-003 | `walkingDistanceRoutes.test.ts` — `should return 503 with error message when HSY WMS endpoint is unavailable` | server:api | Quarantined | — | #10 | 2 / 2 (before quarantine) | #10 | — | - |

**TH-2026-001 notes**: Test introduced in PR #23. In-memory `Map` in `notesService.ts` accumulates state across parallel test runners; ordering of list response is non-deterministic when tests run concurrently. Root cause shares the same mechanism as R-2026-007 (unbounded in-memory growth). 1 PR of data — At-Risk, not yet confirmed Flaky. Promote to Flaky if failure observed again in next PR.

**TH-2026-002 notes**: `GET /walking-distance/:postcode` internally calls HSY WMS (GeoServer `wfs` endpoint). Under load, WMS response time exceeds Jest default 5s timeout (~25% of observed failures at 8-18s response; normal range 7-9s). Intermittent across PRs #10, #17, #23. Mean duration 10.4s; fail duration 16-19s. Recommend: increase timeout to 30s and add retry with exponential back-off, or mock WMS in CI. Flaky confirmed (3 PRs).

**TH-2026-003 notes**: Test exercises real network path to HSY WMS (no mock). When the WMS endpoint is unavailable, the 30s connect timeout fires consistently. Quarantined after PR #10 (2 consecutive failures on main). Target re-evaluation: 2026-05-15. Action needed: implement WMS mock in test setup before re-enabling. See TD-2026-003 (health check probes only server liveness — same root cause).

## Quarantined Tests

| ID | Test / Suite | Component | Quarantined Since | Quarantined Until | Linked TD | Quarantine Reason |
|----|-------------|-----------|------------------|------------------|-----------|-------------------|
| TH-2026-003 | `walkingDistanceRoutes` — HSY WMS unavailable | server:api | PR #10 (2026-02-12) | 2026-05-15 | TD-2026-003 | Requires real WMS network; no mock in CI; 100% fail rate when WMS is down |

## Stable (resolved)

| ID | Test / Suite | Component | Resolved PR | Date |
|----|-------------|-----------|-------------|------|
