# Known Issues

Last updated: 2026-04-21

Test gaps, spec gaps, integration risks, and security gaps accumulated across PR merges. Updated by the merge consolidation agent. Structural debt goes in `tech-debt-register.md`.

**Categories**: test-gap, spec-gap, integration-risk, security
**Priority**: High (blocks release or security baseline), Medium (degrades quality or coverage), Low (minor gap with limited impact)
**Status**: At-Risk (suspected gap, weak signal — filed by Test Investigation agent), Confirmed (explicitly identified in QE PR analysis — filed by merge consolidation)

## Active Issues

| ID | Status | Priority | Category | Description | Source PR | Date | Owner |
|----|--------|----------|----------|-------------|-----------|------|-------|
| KI-2026-008 | Confirmed | High | integration-risk | PostcodeInfoPanel integration with PostcodeNotes component untested; panel wiring with `useNotes` hook has zero test coverage. Failure silently breaks feature for all users. | #23 | 2026-04-01 | - |
| KI-2026-009 | Confirmed | Medium | test-gap | PostcodeNotes edit textarea lacks Escape-key dismissal handler; keyboard users cannot dismiss edit mode without clicking Cancel. E2E test added (skipped) to track when fixed. | #23 | 2026-04-01 | - |
| KI-2026-005 | Confirmed | Medium | test-gap | FavoritesList dropdown lacks Escape-key dismissal handler; keyboard users cannot dismiss the dropdown with Escape. E2E test added (skipped) to track when fixed. | #17 | 2026-02-25 | - |
| KI-2026-006 | Confirmed | Medium | integration-risk | `PostcodeBoundaries.test.tsx` does not exist. Integration path between `useFavorites()` hook and child component wiring (FavoritesList, PostcodeInfoPanel) untested. Simultaneous open-state of FavoritesList and PostcodeSearch dropdowns not validated (R-2026-005). | #17 | 2026-02-25 | - |

## Resolved Issues

| ID | Status | Priority | Category | Description | Resolved PR | Date | Owner |
|----|--------|----------|----------|-------------|-------------|------|-------|
| KI-2026-007 | Resolved | High | spec-gap | 13 notes scenarios added to `postcode-info-panel.feature` covering visibility, CRUD, 500-char limit, char counter, error state, and cross-postcode refresh. | feat/release-gate-agent | 2026-04-21 | - |
| KI-2026-003 | Resolved | High | spec-gap | `favorites.feature` created with 21 scenarios covering heart button toggle, FavoritesList dropdown, remove, persistence, limit enforcement, and corrupted-data handling. | feat/release-gate-agent | 2026-04-21 | - |
| KI-2026-010 | Resolved | High | test-gap | 9 unit tests added to `notes.test.ts` covering fetch/add/update/delete error paths for useNotes hook (Error and non-Error rejections). All pass. | feat/release-gate-agent | 2026-04-21 | - |
| KI-2026-011 | Resolved | High | test-gap | 2 ownership scoping tests added to `notesRoutes.test.ts` documenting current permissive PUT/DELETE behavior. Pass under current implementation; should be updated when auth is added. | feat/release-gate-agent | 2026-04-21 | - |
| KI-2026-004 | Resolved | Medium | test-gap | Error path tests added to `favorites.test.ts`: QuotaExceededError propagation documented; non-array JSON handling verified. | feat/release-gate-agent | 2026-04-21 | - |
| KI-2026-001 | Resolved | Low | test-gap | 5 tests added to `healthRoutes.test.ts` covering 200 response, status field, ISO timestamp, uptime ≥ 0, and no-auth requirement. All pass. | feat/release-gate-agent | 2026-04-21 | - |
| KI-2026-002 | Resolved | Low | spec-gap | 4 health check scenarios added to `api-data-services.feature` covering 200 response, timestamp, uptime, and no-auth requirement. | feat/release-gate-agent | 2026-04-21 | - |
