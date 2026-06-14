# Olist GTM Analytics

Analytics infrastructure for the go-to-market motion of a two-sided e-commerce marketplace.

## Quick Start

1. **dbt (data transformation):** `cd dbt/gtm_analytics_dbt && dbt debug`
2. **Cube (semantic layer):** `cd cube && cp .env.example .env && pip install -r requirements.txt`
3. **Airbyte (ingestion):** See `airbyte/README.md`
4. **Nao (agent):** See `nao/README.md`

## Repository Structure

```
.
├── PROJECT.md              # Source of truth for this project
├── task_brief.md           # Engineering brief and acceptance test
├── README.md               # This file
├── airbyte/                # Data ingestion (custom connectors)
├── dbt/gtm_analytics_dbt/  # Data transformation and marts
├── cube/                   # Semantic layer (metrics & dimensions)
├── nao/                    # Agent runtime (Slack integration)
├── analysis/               # GTM analysis and findings
└── scripts/                # Utility scripts
```

## Phases

1. **Phase 0:** Airbyte custom connectors (`source-attio`, `source-ops`)
2. **Phase 1:** dbt foundation (staging, marts, tests)
3. **Phase 2:** Cube semantic layer
4. **Phase 3:** Nao agent and test suite
5. **Phase 4:** GTM analysis writeup

## Business Questions

The GTM team needs answers to three questions:

1. **Funnel performance** — How does an MQL convert to a closed deal, to a first order, by origin/segment?
2. **Time to payback** — How many days until cumulative commission revenue covers estimated CAC?
3. **Partner eligibility** — Which sellers qualify for the partner program based on quality gates and tier score?

## Docs

- `PROJECT.md` — Canonical business problem, stack, schemas, gotchas, metrics
- `task_brief.md` — Phase-by-phase deliverables and acceptance test
- `dbt/README.md` — dbt setup and running models
- `cube/README.md` — Cube semantic layer and cubes
- `nao/README.md` — Agent context and configuration
- `airbyte/README.md` — Connector setup and deployment

## Notes

- All raw data is in `raw_attio.*` and `raw_ops.*` datasets in BigQuery
- All metrics are defined in Cube, not in dbt models
- The bridge between marketing (Attio) and ops is `seller_id` — treat it as a data contract
- Commission rate and CAC are modeled in dbt seeds, not measured in source data

For more details, see `PROJECT.md`.
