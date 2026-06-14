# Airbyte Custom Connectors

Two custom connectors for the Olist GTM pipeline:

1. **source-attio** — CRM data from Attio (MQLs, closed deals, SDRs, sales activities)
2. **source-ops** — Operational data from production DB (orders, items, sellers, customers, products, payments, reviews, geolocation)

## Setup

See `task_brief.md` Phase 0 for full implementation instructions.

## Sync Schedule

- `raw_attio`: Every 1 hour (CRM moves faster)
- `raw_ops`: Every 6 hours (operational data)

## Connectors

- `connectors/source-attio/` — Attio connector
- `connectors/source-ops/` — Ops DB connector
- `connections/` — Connection configs (landing zones in BigQuery)
