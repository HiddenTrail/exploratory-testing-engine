# Tech Debt Register

Last updated: 2026-04-20

Structural and architectural debt accumulated across PRs. Each item represents a known suboptimal implementation pattern that requires deliberate effort to address. Distinct from the risk register (active threats) and known-issues (test/spec/integration gaps).

**Categories**: architecture, observability, security-hardening, test-infrastructure, performance
**Priority**: must-fix (blocks scalability or security baseline), should-fix (degrades quality over time), nice-fix (improvement opportunity)

## Open Items

| ID | Category | Priority | Component | Source PR | Date | Owner | Description |
|----|----------|----------|-----------|-----------|------|-------|-------------|
| TD-2026-001 | architecture | must-fix | server/src/services/notesService.ts | #23 | 2026-04-01 | - | Notes stored in a bare in-memory `Map` with no persistence — server restart loses all data; no storage abstraction exists for future backend replacement (see R-2026-007) |
| TD-2026-002 | observability | should-fix | server/src/ | #10 | 2026-02-12 | - | No structured logging middleware — every API request produces no structured log entry; blocks AC-OBS-01 and makes production debugging reliant on unstructured stdout |
| TD-2026-003 | observability | should-fix | server/src/index.ts | #10 | 2026-02-12 | - | Health check probes only server process liveness — external dependency connectivity not verified; liveness probe gives a false healthy signal when data sources are down (see R-2026-001) |
| TD-2026-004 | security-hardening | should-fix | server/src/routes/ | #23 | 2026-04-01 | - | No JSON schema or runtime validation on API request bodies — note content accepted without server-side structural validation; maxLength enforced only in the UI component |

## Resolved Items

| ID | Category | Priority | Description | Resolved PR | Date | Owner | Resolution |
|----|----------|----------|-------------|-------------|------|-------|------------|
