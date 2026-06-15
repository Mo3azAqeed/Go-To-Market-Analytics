# Olist GTM Analytics

End-to-end analytics infrastructure for the go-to-market motion of a two-sided e-commerce marketplace. The stack ingests data from Attio CRM and a production ops database into BigQuery, transforms it with dbt, defines every business metric in Cube, and surfaces answers through a Nao agent in Slack — without dashboards.

---

## Business context

Olist is a two-sided marketplace: sellers list products, customers buy them. The GTM team recruits and activates sellers. This repo answers the three questions they ask repeatedly:

**1. Funnel performance**
How does a marketing-qualified lead (MQL) convert to a closed deal, to a first order, to repeat orders? Broken down by lead source (`origin`), business segment, and lead behaviour profile. Which channels are worth doubling down on, and which are burning budget?

**2. Time to seller profitability (payback)**
From the day a deal is closed, how many days until the commission revenue from that seller's orders covers the estimated cost to acquire them (CAC)? The answer determines how long the GTM team must "carry" a seller before they become cash-flow positive.

**3. Partner program eligibility**
Which active sellers qualify for the partner program? Eligibility is gated on four quality dimensions (review score, cancellation rate, on-time delivery, tenure) and ranked by a weighted composite score (GMV velocity, growth, category fit). The agent generates the ranked list on demand.

---

## Architecture

```
Attio CRM ──────────────────────────────────────────────────┐
(leads, deals, reps, activities)                            │
                                                            ▼
                                            dlt (REST API, incremental)
                                                            │
                                                            ▼
                                              BigQuery: raw_attio.*
                                                            │
                                                            │
Ops DB (Postgres) ─────────────────────────────────────────>│ (handled by separate team)
(orders, sellers, items, payments, reviews)                 │
                                                            ▼
                                              BigQuery: raw_ops.*
                                                            │
                                                            ▼
                                                    dbt-core
                                        ┌───────────────────────────────┐
                                        │  staging/attio   staging/ops  │
                                        │       ↓               ↓       │
                                        │         intermediate/          │
                                        │               ↓                │
                                        │  marts/core     marts/gtm      │
                                        │  dim_*, fct_*   seller_lifecycle│
                                        │                 cohort_payback  │
                                        │                 partner_scorecard│
                                        └───────────────────────────────┘
                                                            │
                                                            ▼
                                                          Cube
                                           (gmv, mql_conversion_rate,
                                            days_to_payback, partner_eligibility_score, ...)
                                                            │
                                                            ▼
                                                    Nao + Kimi LLM
                                               (Slack: "Which sellers
                                                qualify for the partner
                                                program this quarter?")
```

---

## Stack

| Layer | Tool | Role |
|---|---|---|
| **Ingestion** | dlt (Python library) | Pulls Attio via REST API into `raw_attio`. No separate server — runs as a Python script on a schedule. |
| **Storage** | BigQuery (`obito-492802`) | Raw, staging, and modeled datasets. All SQL runs here. |
| **Transformation** | dbt-core (BigQuery adapter) | Three-layer model: staging → intermediate → marts. All business logic lives here. |
| **Semantic layer** | Cube (self-hosted Core) | Single source of truth for every metric. Compiles to SQL against BigQuery marts. Nao queries Cube, never raw tables. |
| **Agent** | Nao (self-hosted) | Reads Cube model + dbt repo + business docs as context. Answers questions in Slack. |
| **LLM** | Kimi via OpenRouter | Reasoning engine for Nao. BYO key via env var. |
| **CI/CD** | GitHub Actions | Four workflows: `dlt_ci`, `dbt_ci`, `nao_ci`, `freshness`. All required to pass before merge. |

**Layer rule:** Airbyte ingests, dbt transforms, Cube defines metrics, Nao answers. No business logic in the pipeline. No metric definitions in dbt. No raw table queries in Cube or Nao.

---

## Data sources

### Attio CRM → `raw_attio`
Synced every hour via dlt REST API source.

| Stream | Attio object | Write mode | Cursor |
|---|---|---|---|
| `mqls` | Lists / People | merge | `last_modified` |
| `closed_deals` | Records / Deals (won) | merge | `last_modified` |
| `sdrs` | Workspace members | replace | — |
| `sales_activities` | Notes | append | `created_at` |

### Production ops DB → `raw_ops` *(managed by a separate team)*
Synced every 6 hours via CDC (Postgres logical replication).

| Stream | Grain | Write mode |
|---|---|---|
| `orders` | per order | merge |
| `order_items` | per order × item | merge |
| `sellers` | per seller | merge |
| `customers` | per customer | merge |
| `products` | per product | merge |
| `payments` | per payment | append |
| `reviews` | per review | merge |
| `geolocation` | zip prefix | replace |

**Cross-system bridge:** `closed_deals.seller_id` → `sellers.seller_id`. This is the only join linking a lead's origin to long-term GMV. A dbt singular test enforces referential integrity (threshold: < 2% orphan deals).

---

## Repository layout

```
.
├── PROJECT (1).md              ← Source of truth. This file wins over code.
├── task_brief (1).md           ← Engineering brief and 13-question acceptance test
├── PROBLEMS_AND_LESSONS.md     ← Running log of every build decision
│
├── dlt/                        ← Ingestion (Attio only; ops handled separately)
│   ├── pipelines/
│   │   └── attio_pipeline.py   ← Entry point: run this to load Attio → BigQuery
│   ├── sources/
│   │   └── attio/
│   │       ├── __init__.py     ← 4 resources with cursors, write dispositions, _extracted_at
│   │       └── tests/          ← Unit tests (HTTP mocked; no network required)
│   ├── .dlt/
│   │   └── config.toml         ← Non-secret config (mql_list_id, BQ project)
│   ├── requirements.txt
│   └── README.md               ← Setup, env vars, troubleshooting, adding streams
│
├── dbt/gtm_analytics_dbt/      ← All SQL transformations
│   ├── models/
│   │   ├── staging/attio/      ← stg_attio__*.sql (light typing, no business logic)
│   │   ├── staging/ops/        ← stg_ops__*.sql
│   │   ├── intermediate/       ← int_*.sql (complex joins, not exposed to Cube)
│   │   └── marts/
│   │       ├── core/           ← dim_seller, fct_orders, fct_payments, ...
│   │       └── gtm/            ← seller_lifecycle, cohort_payback, partner_scorecard
│   ├── seeds/
│   │   ├── commission_rates.csv ← 15% placeholder per business_segment
│   │   └── cac_estimates.csv   ← Rough CAC per lead origin
│   ├── tests/
│   │   └── seller_id_bridge_integrity.sql ← Fails if > 2% of deals have unknown seller
│   └── models/sources.yml      ← raw_attio.* and raw_ops.* with freshness SLAs
│
├── cube/                       ← Semantic layer
│   └── model/
│       ├── cubes/              ← sellers, funnel, orders, partner_eligibility
│       └── views/              ← gtm_funnel_view, seller_economics_view, partner_program_view
│
├── nao/                        ← Agent context
│   ├── RULES.md                ← Behavioural rules (always use Cube; never query raw)
│   ├── docs/
│   │   ├── business_defs.md    ← Plain-English metric definitions with worked examples
│   │   └── glossary.md         ← Portuguese ↔ English category names, Olist jargon
│   ├── queries/
│   │   └── example_queries.md  ← 15+ golden NL → Cube query examples
│   └── tests/
│       └── question_set.yaml   ← 30+ agent unit tests (≥ 90% correct to pass CI)
│
└── analysis/                   ← GTM findings memo (Phase 4 deliverable)
```

---

## Quick start — ingestion (Attio)

```bash
cd dlt
pip install -r requirements.txt

# Set credentials as environment variables (no secrets file needed)
export SOURCES__ATTIO_SOURCE__API_TOKEN="your-attio-api-token"
export SOURCES__ATTIO_SOURCE__MQL_LIST_ID="your-mql-list-id"
export DESTINATION__BIGQUERY__CREDENTIALS__PROJECT_ID="obito-492802"
export DESTINATION__BIGQUERY__CREDENTIALS__PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
export DESTINATION__BIGQUERY__CREDENTIALS__CLIENT_EMAIL="sa@obito-492802.iam.gserviceaccount.com"
export DESTINATION__BIGQUERY__CREDENTIALS__CLIENT_ID="..."
export DESTINATION__BIGQUERY__CREDENTIALS__TOKEN_URI="https://oauth2.googleapis.com/token"

python pipelines/attio_pipeline.py
```

See [`dlt/README.md`](dlt/README.md) for the full env var table and troubleshooting guide.

---

## Quick start — transformation (dbt)

```bash
cd dbt/gtm_analytics_dbt
dbt deps
dbt debug          # verify BigQuery connection
dbt build          # run all models + tests
dbt source freshness  # check raw table staleness
```

---

## Canonical metrics

All defined in Cube. Plain-English versions in `nao/docs/business_defs.md`.

| Metric | Definition |
|---|---|
| `mql_count` | Distinct MQL IDs in `stg_attio__mqls` |
| `mql_to_close_rate` | `closed_deal_count / mql_count` by origin, segment, cohort |
| `gmv` | `SUM(order_items.price)` on realized statuses (delivered, shipped, invoiced) |
| `commission_revenue` | `gmv × commission_rate` (rate from seed, per segment) |
| `days_to_first_order` | `first_order_at − won_date` in days |
| `days_to_payback` | First day cumulative commission ≥ estimated CAC |
| `partner_eligibility_score` | Weighted composite of GMV velocity, growth, and category fit |

---

## CI/CD

Four GitHub Actions workflows, all required to pass before merge to `main`:

| Workflow | Trigger | What it does |
|---|---|---|
| `dlt_ci.yml` | Changes to `dlt/**` | Unit tests → dry-run → full sync (main only) |
| `dbt_ci.yml` | Changes to `dbt/**` or `cube/**` | `dbt parse` → `dbt build --select state:modified+` → `dbt test` → `cube validate` |
| `nao_ci.yml` | Changes to `nao/**` or `cube/**` | `nao test` — must pass ≥ 90% correct, ≥ 95% answered |
| `freshness.yml` | Nightly cron (06:00 UTC) | `dbt source freshness` — Slack alert on failure |

Credentials are passed as GitHub Actions secrets mapped to environment variables. No credential files are written to disk during CI.

---

## Key gotchas

Read [`PROJECT (1).md`](PROJECT%20(1).md) §6 before writing any SQL. The most costly ones:

- **`order_items` fans out.** Aggregate to order grain *before* joining to `orders` or you multiply revenue.
- **GMV ≠ payment value.** Use `SUM(order_items.price)` filtered to realized statuses, not `payments.payment_value`.
- **`customer_id` ≠ `customer_unique_id`.** Repeat-customer analysis must use `customer_unique_id`.
- **`seller_id` drift.** Attio operators paste IDs manually — typos happen. The bridge integrity test catches it.
- **Reviews are sparse.** Always `LEFT JOIN`. Missing review ≠ zero score.
