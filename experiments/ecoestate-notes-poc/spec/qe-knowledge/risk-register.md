# Risk Register

Last updated: 2026-04-20

Accumulated risks across PR merges. Each risk has a stable ID (`R-YYYY-NNN`) assigned by the merge consolidation agent.

**Severity levels**: Critical, High, Medium, Low
**Status**: Open, Mitigated, Resolved
**Root Cause**: `timing` | `shared-state` | `validation-gap` | `infrastructure` | `design` | `-`

## Open Risks

| ID | Risk | Severity | Root Cause | Component | Source PR | Date | Status | Owner |
|----|------|----------|------------|-----------|-----------|------|--------|-------|
| R-2026-002 | `saveFavorites()` calls `localStorage.setItem()` without try-catch — `QuotaExceededError` uncaught | High | validation-gap | client/src/utils/favorites.ts | #17 | 2026-02-25 | Open | - |
| R-2026-003 | `loadFavorites()` casts parsed JSON to `FavoritePostcode[]` without structural validation | High | validation-gap | client/src/utils/favorites.ts | #17 | 2026-02-25 | Open | - |
| R-2026-006 | PUT and DELETE `/api/notes/:id` endpoints accept note ID with no ownership verification — any client that knows or guesses a note ID can modify or delete another session's notes | High | validation-gap | server/src/routes/notesRoutes.ts, server/src/services/notesService.ts | #23 | 2026-04-01 | Open | - |
| R-2026-001 | Health endpoint does not check external dependencies | Medium | design | server/src/index.ts | #10 | 2026-02-12 | Open | - |
| R-2026-004 | FavoritesList dropdown has no Escape-key handler | Medium | design | client/src/components/FavoritesList.tsx | #17 | 2026-02-25 | Open | - |
| R-2026-005 | FavoritesList and PostcodeSearch dropdowns share viewport zone with no mutual exclusion | Medium | design | client/src/components/FavoritesList.tsx, client/src/components/PostcodeSearch | #17 | 2026-02-25 | Open | - |
| R-2026-007 | In-memory `Map` notes storage has no cap on total note count per postcode — sustained concurrent use accumulates notes unboundedly in heap; eventual OOM crash affects all features | Medium | design | server/src/services/notesService.ts | #23 | 2026-04-01 | Open | - |

## Resolved Risks

| ID | Risk | Severity | Root Cause | Source PR | Resolved PR | Date | Resolution | Owner |
|----|------|----------|------------|-----------|-------------|------|------------|-------|
