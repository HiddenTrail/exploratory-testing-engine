# Acceptance Criteria Catalog

Non-functional requirements and system properties for EcoEstate. Each criterion defines a verifiable property with observability signals and specification coverage mapping.

## How to Read This Document

- **Criterion ID**: `AC-{CATEGORY}-{NN}` — unique, stable identifier cited by the Acceptance Criteria agent
- **Categories**: PERF (Performance), RES (Resilience), SEC (Security), OBS (Observability), DATA (Data Quality), A11Y (Accessibility), UX (User Experience), INT (Integration Contracts)
- **Scope**: local | system | integration — whether a criterion is verifiable within one repo (local), requires evidence from multiple repos (system), or verifies interface contracts between services (integration)
- **Signal status**: Implemented | Partial | Not Implemented
- **Verification tier**: T1 (code inspection), T2 (structured logging), T3 (metrics pipeline)

## AC-PERF: Performance

### AC-PERF-01: API Response Latency

- **Statement**: All API endpoints respond within 500ms at p95 under normal load
- **Scope**: system
- **Owning repo**: ecoestate (measurement origin; full end-to-end signal requires consumer repos)
- **Signal**: `http_request_duration_seconds` histogram on `/api/*` routes
- **Signal status**: Not Implemented
- **Verification tier**: T3
- **Spec coverage**: None (system property, not behavioral scenario)
- **Code evidence**: No response time measurement exists

### AC-PERF-02: Map Render Performance

- **Statement**: Map initializes and renders postcode boundaries within 3s on standard connection
- **Scope**: local
- **Signal**: `map_render_duration_ms` browser performance mark
- **Signal status**: Not Implemented
- **Verification tier**: T3
- **Spec coverage**: map-interface.feature (functional rendering only, no timing assertions)
- **Code evidence**: Leaflet renders GeoJSON; no performance instrumentation

## AC-RES: Resilience

### AC-RES-01: External API Graceful Degradation

- **Statement**: When an external data source is unavailable, the system serves cached data and indicates staleness
- **Scope**: system
- **Owning repo**: ecoestate (graceful degradation must also hold in consuming repos — see AC-INT-03)
- **Signal**: `external_api_error_total` counter, `cache_fallback_activated` event log
- **Signal status**: Not Implemented (cache exists but no fallback signaling)
- **Verification tier**: T2
- **Spec coverage**: walking-distance.feature has 1 error scenario; no other external API failure specs
- **Code evidence**: In-memory cache with 24h TTL exists; no explicit fallback logic

### AC-RES-02: Cache Effectiveness

- **Statement**: Cache hit rate exceeds 90% during normal operation
- **Scope**: local
- **Signal**: `cache_hit_total` / `cache_miss_total` counters
- **Signal status**: Not Implemented
- **Verification tier**: T3
- **Spec coverage**: api-data-services.feature covers 24h TTL behavior
- **Code evidence**: node-cron scheduled fetching; in-memory cache

## AC-SEC: Security

### AC-SEC-01: CORS Enforcement

- **Statement**: Production API rejects requests from unauthorized origins
- **Scope**: local
- **Signal**: `cors_rejected_total` counter, response `Access-Control-Allow-Origin` header
- **Signal status**: Not Implemented (CORS configured but not monitored)
- **Verification tier**: T1 (header presence verifiable via code inspection)
- **Spec coverage**: api-data-services.feature (2 scenarios: dev origin allowed, preflight)
- **Code evidence**: Dynamic CORS in Express middleware

### AC-SEC-02: Content Security Policy

- **Statement**: Production responses include strict CSP headers preventing inline script execution
- **Scope**: local
- **Signal**: `Content-Security-Policy` header presence in responses
- **Signal status**: Partial (Nginx header configured per ARCHITECTURE.md)
- **Verification tier**: T1
- **Spec coverage**: None
- **Code evidence**: Nginx config with CSP header; permissive dev meta tag

### AC-SEC-03: Input Sanitization

- **Statement**: All user inputs are sanitized before rendering in UI or processing in API
- **Scope**: local
- **Signal**: No XSS payloads execute; input validation logs
- **Signal status**: Not Implemented (code exists but no monitoring)
- **Verification tier**: T1 (code inspection for sanitization functions)
- **Spec coverage**: postcode-search.feature (functional search behavior only)
- **Code evidence**: React JSX escaping + custom escapeHTML for Leaflet popups

## AC-OBS: Observability

### AC-OBS-01: Structured Request Logging

- **Statement**: Every API request produces a structured log entry with method, path, status, duration, correlation ID
- **Scope**: system
- **Owning repo**: ecoestate (correlation ID must also be propagated by all callers — see AC-INT-02)
- **Signal**: Log entries in Azure Log Analytics with structured fields
- **Signal status**: Not Implemented
- **Verification tier**: T2
- **Spec coverage**: None
- **Code evidence**: No structured logging middleware

### AC-OBS-02: Health Check Endpoint

- **Statement**: `/health` endpoint returns system status including external dependency connectivity
- **Scope**: local
- **Signal**: Health check response, Azure Container Apps liveness probe
- **Signal status**: Partial (endpoint exists and tested; external dependency check not yet implemented)
- **Verification tier**: T1 (endpoint existence verifiable via code inspection)
- **Spec coverage**: api-data-services.feature (4 scenarios: 200 response, status field, ISO timestamp, uptime, no-auth requirement — KI-2026-002 closed)
- **Code evidence**: `/health` endpoint returns 200 with status, timestamp, uptime; 5 unit tests pass in `healthRoutes.test.ts`; no external dependency connectivity check

### AC-OBS-03: External Dependency Monitoring

- **Statement**: Each external API call is logged with latency, status, and error detail
- **Scope**: local
- **Signal**: `external_api_request_duration_seconds` histogram per dependency
- **Signal status**: Not Implemented
- **Verification tier**: T2
- **Spec coverage**: None
- **Code evidence**: No outbound request instrumentation

## AC-DATA: Data Quality

### AC-DATA-01: Data Freshness

- **Statement**: Property price and boundary data is refreshed within 24 hours of cache expiry
- **Scope**: system
- **Owning repo**: ecoestate (freshness signal must be visible to all consumers)
- **Signal**: `data_last_refresh_timestamp` gauge per data source, `data_age_seconds` metric
- **Signal status**: Not Implemented (cron exists but no freshness metric)
- **Verification tier**: T3
- **Spec coverage**: api-data-services.feature (24h TTL specified)
- **Code evidence**: node-cron scheduled fetching with 24h interval

### AC-DATA-02: Data Completeness Indicator

- **Statement**: UI indicates when data is unavailable for a postcode rather than showing empty/broken state
- **Scope**: local
- **Signal**: N/A display events in UI analytics
- **Signal status**: Partial (N/A handling exists in some views)
- **Verification tier**: T1
- **Spec coverage**: property-price-heatmap.feature (N/A scenario), postcode-info-panel.feature (N/A handling)
- **Code evidence**: N/A rendering for missing prices

## AC-A11Y: Accessibility

### AC-A11Y-01: Keyboard Navigation

- **Statement**: All interactive elements are reachable and operable via keyboard
- **Scope**: local
- **Signal**: Accessibility audit score (axe-core), focus-visible indicators
- **Signal status**: Improved (PostcodeSearch keyboard nav implemented and tested; not yet systematic across all components)
- **Verification tier**: T1 (ARIA attributes and tabindex verifiable via code inspection)
- **Spec coverage**: postcode-search.feature (keyboard nav for search: ArrowDown, Enter, Escape)
- **Code evidence**: PostcodeSearch has ARIA `listbox`/`option` roles, `aria-selected`, keyboard handler for ArrowDown/Up/Enter/Escape; 3 keyboard navigation unit tests pass; no systematic ARIA audit across all interactive elements

## AC-UX: User Experience

### AC-UX-01: Loading State Feedback

- **Statement**: Every async operation shows a loading indicator within 200ms
- **Scope**: local
- **Signal**: UI interaction traces, loading state render events
- **Signal status**: Improved (walking distance and notes loading states tested; not yet systematic)
- **Verification tier**: T1
- **Spec coverage**: walking-distance.feature (loading state), visualization-controls.feature (loading during switch)
- **Code evidence**: `walkingDistanceLoading` prop renders "Loading..." in PostcodeInfoPanel (unit tested); notes loading state covered; not systematic across all async paths

### AC-UX-02: Error State Communication

- **Statement**: User-facing errors display actionable messages, not technical stack traces
- **Scope**: local
- **Signal**: Error boundary render events, user-visible error message content
- **Signal status**: Improved (error paths tested for notes and favorites; not yet systematic)
- **Verification tier**: T1
- **Spec coverage**: walking-distance.feature (error display scenario), postcode-info-panel.feature (notes error state)
- **Code evidence**: `useNotes` error paths tested (9 tests); favorites QuotaExceededError documented; not systematic across all API call sites

## AC-NOTES: Notes

### AC-NOTES-01: Note Content Validation

- **Statement**: Notes are validated for content (non-empty) and length (≤ 500 characters); UI displays accurate character count in real time
- **Scope**: local
- **Signal**: Save button disabled for empty/overlength input; character counter updates on each keystroke
- **Signal status**: Improved (validation and counter tested; error state not yet covered by automated tests)
- **Verification tier**: T1 (validation logic verifiable via code inspection and unit tests)
- **Spec coverage**: postcode-info-panel.feature (13 notes scenarios: CRUD, 500-char limit, char counter, error state, cross-postcode refresh — KI-2026-007 closed)
- **Code evidence**: `useNotes` hook implements add/update/delete; character counter and 500-char limit in PostcodeNotes component; unit tests cover hook error paths

## AC-INT: Integration Contracts

Integration criteria verify the interface contracts between services. Evidence is assessed against `service-catalog.yaml` in the hub repo, not against local code alone. A complete catalog entry for the relevant endpoint constitutes T1 evidence for AC-INT-01. An incomplete or absent catalog entry is a Contract Gap.

### AC-INT-01: API Contract Documentation

- **Statement**: All externally consumed API endpoints are documented in `service-catalog.yaml` with path, method, parameters, and response schema
- **Scope**: integration
- **Signal**: Presence of complete endpoint entries in `service-catalog.yaml`
- **Signal status**: Partial (catalog exists; schema hashes and semver versioning strategy not yet added)
- **Verification tier**: T1 (catalog inspection)
- **Spec coverage**: None
- **Code evidence**: `service-catalog.yaml` — ecoestate-api endpoints documented; no versioning strategy yet

### AC-INT-02: Correlation ID Propagation

- **Statement**: All cross-service HTTP calls propagate a `X-Correlation-ID` header so requests can be traced end-to-end
- **Scope**: integration
- **Signal**: `X-Correlation-ID` header present in outbound requests from consumer repos; logged in structured request logs
- **Signal status**: Not Implemented
- **Verification tier**: T2 (log inspection)
- **Spec coverage**: None
- **Code evidence**: No correlation ID middleware in EcoEstate; no forwarding logic in ecoestate-analytics stub

### AC-INT-03: Breaking Changes Declared Before Deployment

- **Statement**: Any breaking change to an API endpoint consumed by another service is documented in `service-catalog.yaml` and communicated to consuming teams before the change is deployed
- **Scope**: integration
- **Signal**: Change Analysis cross-repo blast radius section classifies breaking vs. additive for every changed endpoint
- **Signal status**: Partial (Change Analysis prompt updated to detect this; automated dispatch not yet implemented — Phase 3)
- **Verification tier**: T1 (change analysis artifact inspection)
- **Spec coverage**: None
- **Code evidence**: N/A — process criterion, not code criterion

### AC-INT-04: Consumer Usage Patterns Match Catalog

- **Statement**: The `endpoints_used` and `notes` fields in `service-catalog.yaml` `consumed_by` entries accurately reflect actual call site code in each consuming repo
- **Scope**: integration
- **Signal**: Contract Validation agent audit report (`qe/output/contract-validation/`)
- **Signal status**: Not Implemented (Contract Validation agent not yet created — Phase 4)
- **Verification tier**: T1 (code inspection via Grep in consuming repos)
- **Spec coverage**: None
- **Code evidence**: ecoestate-analytics is a stub repo; catalog entry is author-declared, not code-verified
