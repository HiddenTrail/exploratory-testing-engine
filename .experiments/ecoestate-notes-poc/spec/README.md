# EcoEstate

Interactive map visualizing property prices and environmental quality in the Helsinki metropolitan area. Built on open data from Statistics Finland, HSY, and OpenStreetMap.

> **QES role**: Producer spoke in the [HiddenTrail/qes](https://github.com/HiddenTrail/qes) hub-and-spoke QE model. The EcoEstate API is consumed by [HiddenTrail/ecoestate-analytics](https://github.com/HiddenTrail/ecoestate-analytics).

## What it does

- **Property price heatmap** — choropleth map of median prices (€/m²) per postcode for any year 2010–2024
- **Price trend layer** — 5-year trend visualization per postcode, toggleable alongside the heatmap
- **Green spaces layer** — parks and forests from OpenStreetMap overlaid on the map
- **Postcode search** — fuzzy search by postcode number or district name
- **Walking distance to transit** — HSY WMS data per postcode centroid

## Tech stack

| Layer | Technology |
|-------|------------|
| Frontend | React, TypeScript, Vite, Leaflet.js, Axios |
| Backend | Node.js, Express, TypeScript, node-cron |
| Infra | Docker, Azure Container Apps, Terraform |
| CI | GitHub Actions |
| Tests | Frontend: Vitest + React Testing Library. Backend: Jest + Supertest |

## Running locally

### Without Docker

```bash
# Backend (port 3001)
cd server && npm install && npm run dev

# Frontend (port 3000) — separate terminal
cd client && npm install && npm run dev
```

### With Docker Compose

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:3001

Hot reloading is enabled for both services. `node_modules` live in Docker named volumes to avoid conflicts with local directories.

## Running tests

```bash
# Backend
cd server && npm test

# Frontend
cd client && npm test

# With coverage
cd server && npm run test:coverage
cd client && npm run test:coverage
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/property-prices?year=YYYY` | Per-postcode prices for a year |
| `GET` | `/api/property-prices/trends?endYear=YYYY` | 5-year trend ending at endYear |
| `GET` | `/api/postcodes` | All postcode boundaries (GeoJSON) |
| `GET` | `/api/postcodes/search?q=…` | Fuzzy search by postcode or district name |
| `GET` | `/api/map-data/green-spaces` | Green space polygons (GeoJSON) |

Full contract: [`service-catalog.yaml`](https://github.com/HiddenTrail/qes/blob/main/service-catalog.yaml) in the hub repo.

## External data sources

| Data | Source | Notes |
|------|--------|-------|
| Property prices | Statistics Finland PX-Web API | Cached 24 h |
| Postcode boundaries | HSY WFS | EPSG:3879 → EPSG:4326 |
| Walking distance to transit | HSY WMS GetFeatureInfo | Per postcode centroid |
| Green spaces | OpenStreetMap Overpass API | Cached in-process |

## Building and deploying to Azure

Images are built and pushed to Azure Container Registry using `scripts/acr_upload.sh`. Infrastructure is managed by Terraform in `tf/`.

```bash
# Build and push version 1.2.0 to the dev ACR
./scripts/acr_upload.sh -v 1.2.0 -w dev

# Promote the same image to staging, then prod
./scripts/acr_upload.sh -v 1.2.0 -w staging
./scripts/acr_upload.sh -v 1.2.0 -w prod
```

See `tf/README.md` for Terraform setup and `scripts/acr_upload.sh` for full usage.

## CI / QE pipeline

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| `CI Pipeline` | Pull request | ESLint, Trivy, backend tests, frontend tests |
| `QE Agents` | After CI passes | Runs the full QE agent pipeline (change analysis, risk, specs, test strategy) |
| `QE Merge` | PR merged to main | Merge consolidation — updates `qe/knowledge/` |

The QE pipeline detects API changes and automatically notifies `HiddenTrail/ecoestate-analytics` via `repository_dispatch` when a PR touches an endpoint the analytics spoke consumes.

**Required secrets** (Settings → Secrets → Actions):

| Secret | Purpose |
|--------|---------|
| `AWS_ACCESS_KEY_ID` | Bedrock access for Claude Code Action |
| `AWS_SECRET_ACCESS_KEY` | Bedrock access for Claude Code Action |
| `AWS_REGION` | `eu-north-1` |
| `CROSS_REPO_DISPATCH_TOKEN` | Fine-grained PAT — `contents: write` on `ecoestate-analytics` and `qes` |

## Repository structure

```
client/          React/Vite frontend
server/          Node.js/Express backend
browser-tests/   Playwright end-to-end tests
specifications/  BDD feature files and acceptance criteria
qe/knowledge/    Local QE knowledge layer (risk register, coverage tracker, known issues)
qe/output/       QE artifacts generated per PR
.agents/         QE agent prompts (sourced from hub — do not modify locally)
AGENTS.md        QE agent pipeline contract
CONTEXT.md       Product and tech context for QE agents
service-catalog.yaml  Cross-repo API dependency map (source of truth: HiddenTrail/qes)
tf/              Terraform infrastructure (Azure Container Apps)
scripts/         ACR image push and deploy scripts
docker-compose.yml    Local development stack
```
