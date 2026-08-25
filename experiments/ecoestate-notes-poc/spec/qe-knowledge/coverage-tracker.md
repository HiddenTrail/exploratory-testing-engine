# Coverage Tracker

Last updated: 2026-04-20

Tracks acceptance criteria signal status and specification coverage per feature file. Updated by the merge consolidation agent after each PR merge.

**Signal status progression**: `Not Implemented` → `Partial` → `Improved` → `Implemented`
- `Not Implemented` — no code or test evidence the criterion is being addressed
- `Partial` — some infrastructure or code exists but criterion not fully met
- `Improved` — meaningful progress made in a PR; criterion closer to met but not yet fully verified
- `Implemented` — criterion is verifiably met with test coverage and spec alignment

**Verification tiers**: T1 = unit/integration test (automated, local) · T2 = system/API test (automated, integration layer) · T3 = non-functional / performance test (manual or specialist tooling)

## Acceptance Criteria Signal Status

| Criterion ID | Statement | Signal Status | Verification Tier |
|-------------|-----------|---------------|-------------------|
| AC-PERF-01 | API Response Latency (p95 < 500ms) | Not Implemented | T3 |
| AC-PERF-02 | Map Render Performance (< 3s) | Not Implemented | T3 |
| AC-RES-01 | External API Graceful Degradation | Not Implemented | T2 |
| AC-RES-02 | Cache Effectiveness (> 90% hit rate) | Not Implemented | T3 |
| AC-SEC-01 | CORS Enforcement | Not Implemented | T1 |
| AC-SEC-02 | Content Security Policy | Partial | T1 |
| AC-SEC-03 | Input Sanitization | Not Implemented | T1 |
| AC-OBS-01 | Structured Request Logging | Not Implemented | T2 |
| AC-OBS-02 | Health Check Endpoint | Partial | T1 |
| AC-OBS-03 | External Dependency Monitoring | Not Implemented | T2 |
| AC-DATA-01 | Data Freshness (24h refresh) | Not Implemented | T3 |
| AC-DATA-02 | Data Completeness Indicator | Partial | T1 |
| AC-A11Y-01 | Keyboard Navigation | Improved | T1 |
| AC-NOTES-01 | Note Content Validation | Improved | T1 |
| AC-UX-01 | Loading State Feedback (< 200ms) | Improved | T1 |
| AC-UX-02 | Error State Communication | Improved | T1 |

## Specification Coverage Summary

| Feature File | Scenarios | Domain Area | Tags | Coverage Notes |
|-------------|-----------|-------------|------|----------------|
| map-interface.feature | 8 | UI/Map | @map @ui @leaflet | None identified |
| property-price-heatmap.feature | 14 | Visualization | @visualization @prices @heatmap | None identified |
| price-trend-analysis.feature | 16 | Visualization | @visualization @trends @prices | None identified |
| postcode-search.feature | 18 | UI/Search | @search @ui @api | None identified |
| postcode-info-panel.feature | 33 | UI/Panel | @panel @ui @prices @walking | +13 notes scenarios added (KI-2026-007 closed) |
| walking-distance.feature | 18 | Data/API | @walking @hsy @wms @api | None identified |
| visualization-controls.feature | 15 | UI/Controls | @controls @ui @visualization | None identified |
| api-data-services.feature | 29 | API/Backend | @api @backend @cache @cors | +4 health check scenarios added (KI-2026-002 closed) |
| favorites.feature | 21 | UI/Favorites | @favorites @ui @localStorage @accessibility | New file — full favorites coverage (KI-2026-003 closed) |

**Total: 172 scenarios across 9 feature files** (+38 from baseline of 134)

## Code Coverage Baseline (2026-04-21)

Coverage reporting enabled via Jest (server) and Vitest + @vitest/coverage-v8 (client).
LCOV artifacts uploaded to CI on every PR as `ci-backend-coverage-lcov` and `ci-frontend-coverage-lcov`.

| Layer | Statements | Branches | Functions | Lines | Note |
|-------|-----------|---------|-----------|-------|------|
| Server (Jest) | 63.96% (387/605) | 43.95% (109/248) | 64.28% (45/70) | 64.24% (372/579) | 4 suites fail (DB integration) |
| Client (Vitest) — baseline | 28.14% (365/1297) | 79.81% (87/109) | 78.94% (30/38) | 28.14% (365/1297) | Initial — 0 component/hook tests |
| Client (Vitest) — 2026-04-21 | **42.02% (545/1297)** | **86.70% (137/158)** | 77.27% (34/44) | **42.02% (545/1297)** | After Steps 3+6: +14pp |

**Ceiling assessment**: Remaining ~58% untested are in Leaflet-dependent components (`App.tsx`, `MapComponent.tsx`, `PostcodeBoundaries.tsx`, `YearSlider.tsx`, `PeriodSlider.tsx`). Not realistically unit-testable; realistic ceiling ~45%. E2E tests cover these behaviorally.
