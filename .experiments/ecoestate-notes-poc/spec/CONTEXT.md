# EcoEstate — Project Context

## What is EcoEstate

EcoEstate is a web application that provides interactive map-based visualizations correlating property prices with environmental quality indicators in Finland's Helsinki metropolitan region.

**Problem**: Property buyers struggle to understand how environmental factors impact property values and quality of life. Current real estate platforms focus on property details without connecting them to green spaces, public transport access, or other environmental indicators.

**Solution**: EcoEstate bridges this gap by combining property price data with environmental quality indicators on a single interactive map, providing correlation insights and supporting more informed real estate decisions.

## Target Users

- **Property Buyers** — individuals making informed purchasing decisions
- **Real Estate Professionals** — agents and analysts seeking data-driven insights
- **Urban Planners** — professionals studying environment-property value relationships
- **Researchers** — academics investigating environmental factors and real estate markets

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React, TypeScript, Vite, Leaflet.js, Axios |
| Backend | Node.js, Express, TypeScript, node-cron |
| Infra | Docker, Azure Container Apps, Terraform |
| CI/CD | GitHub Actions (lint, test; build/deploy planned) |
| Testing | Frontend: Vitest, React Testing Library, happy-dom. Backend: Jest, Supertest |

## External Data Sources

| Data Type | Source | API | Format |
|-----------|--------|-----|--------|
| Property Prices | Statistics Finland | PX-Web API (`stat.fi`) | JSON |
| Postcode Boundaries | HSY | WFS (`hsy.fi`) | GeoJSON (EPSG:3879 → EPSG:4326) |
| Walking Distance | HSY | WMS GetFeatureInfo (`hsy.fi`) | XML |
| Green Spaces | OpenStreetMap | Overpass API (`overpass-api.de`) | GeoJSON |
| Public Transport | Digitransit | Digitransit API | JSON |

## Architecture Overview

- **Frontend**: React SPA served by Nginx (production) or Vite dev server (development). Leaflet.js renders interactive map with choropleth layers, markers, and tooltips.
- **Backend**: Express REST API with in-memory caching (24h TTL) and scheduled data fetching via node-cron. Dynamic CORS policy based on environment.
- **Data Flow**: External APIs → Backend cache → REST endpoints → Frontend map visualization.
- **Deployment**: Docker containers on Azure Container Apps. Terraform manages infrastructure. Nginx reverse-proxies `/api` requests to backend.

## Key Design Patterns

- **Layer-based visualization**: Togglable data layers (price heatmap, price trends, green spaces, transport) rendered as choropleth maps and marker clusters
- **Unidirectional data flow**: React hooks for state management, API service modules for backend communication
- **RESTful API design**: Standardized response formats, data aggregation and transformation on backend
- **Scheduled data pipeline**: Backend fetches and caches external API data on cron schedule, serving cached results to frontend

## References

- Functional specifications: `specifications/features/*.feature` (Gherkin format)
- Domain glossary: `specifications/GLOSSARY.md`
- Architecture deep-dive: `ARCHITECTURE.md`
